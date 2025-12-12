# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import base64
import logging

_logger = logging.getLogger(__name__)

try:
    from google.cloud import bigquery
    from google.oauth2 import service_account
    import vertexai
    from google.cloud import aiplatform
    from vertexai.generative_models import GenerativeModel
    from vertexai.language_models import TextGenerationModel
except ImportError:
    bigquery = None
    service_account = None
    vertexai = None

class BiDashboardItem(models.Model):
    _name = 'bi.dashboard.item'
    _description = 'BI Dashboard Item'

    name = fields.Char(string="Title", required=True)
    prompt = fields.Text(string="Question", required=True)
    sql_query = fields.Text(string="Generated SQL", readonly=True)
    chart_type = fields.Selection([
        ('bar', 'Bar Chart'),
        ('line', 'Line Chart'),
        ('pie', 'Pie Chart'),
        ('doughnut', 'Doughnut Chart'),
        ('polarArea', 'Polar Area Chart'),
        ('radar', 'Radar Chart'),
    ], string="Chart Type", default='bar')
    chart_data = fields.Text(string="Chart Data (JSON)", readonly=True)
    
    def _get_bq_client(self):
        """Helper to get BigQuery Client."""
        settings = self.env['ir.config_parameter'].sudo()
        json_b64 = settings.get_param('odoo_gen_bi.gcp_credentials_json')
        
        if not json_b64:
             raise UserError(_("GCP Credentials not found."))
        
        try:
            creds_data = json.loads(base64.b64decode(json_b64))
            credentials = service_account.Credentials.from_service_account_info(creds_data)
            return bigquery.Client(credentials=credentials, project=credentials.project_id), credentials
        except Exception as e:
            raise UserError(_("Failed to create BigQuery Client: %s") % str(e))

    def _get_schema_summary(self, client, dataset_id):
        """Fetch schema summary for the context."""
        schema_summary = ""
        dataset_ref = f"{client.project}.{dataset_id}"
        
        try:
            tables = list(client.list_tables(dataset_ref))
            for table in tables:
                t = client.get_table(table)
                schema_summary += f"Table: {table.table_id}\nColumns:\n"
                for s in t.schema:
                    schema_summary += f"- {s.name} ({s.field_type})\n"
                schema_summary += "\n"
        except Exception as e:
            _logger.error(f"Error fetching schema: {e}")
            schema_summary = "Error fetching schema."
            
        return schema_summary

    def generate_chart_data(self):
        """Main method called by UI to generate chart."""
        self.ensure_one()
        client, credentials = self._get_bq_client()
        dataset_id = self.env['ir.config_parameter'].sudo().get_param('odoo_gen_bi.bq_dataset_id', 'odoo_bi')
        
        # 1. Get Schema
        schema_summary = self._get_schema_summary(client, dataset_id)
        
        # 2. Call Gemini
        config = self.env['ir.config_parameter'].sudo()
        user_location = config.get_param('odoo_gen_bi.gcp_location', 'us-central1')
        user_model_name = config.get_param('odoo_gen_bi.ai_model_name', 'gemini-1.5-flash')
        
        # DIAGNOSTIC LOGGING
        _logger.info(f"OdooGenBI: Starting AI Generation...")
        _logger.info(f"OdooGenBI: Project ID from Client: {client.project}")
        if hasattr(credentials, 'service_account_email'):
             _logger.info(f"OdooGenBI: Service Account: {credentials.service_account_email}")
        _logger.info(f"OdooGenBI: Target Location: {user_location} (and fallbacks in us-central1)")
        
        # Strategy: Try user config, then fallbacks in us-central1
        attempts = [
            {'model': user_model_name, 'location': user_location},
            {'model': 'gemini-1.5-flash', 'location': 'us-central1'},
            {'model': 'gemini-1.5-pro', 'location': 'us-central1'},
            {'model': 'gemini-1.0-pro', 'location': 'us-central1'},
            {'model': 'gemini-pro', 'location': 'us-central1'},
        ]
        
        ai_result = None
        last_error = None
        
        for attempt in attempts:
            try:
                # Avoid retrying the exact same combination if user config matches a fallback
                # check skipped for simplicity, overhead is low
                
                vertexai.init(project=client.project, location=attempt['location'], credentials=credentials)
                
                response_text_raw = ""

                if 'bison' in attempt['model']:
                    # PaLM Model
                    model = TextGenerationModel.from_pretrained(attempt['model'])
                    # PaLM prompt needs to be slightly different (no system prompt arg, just one string)
                    full_prompt = f"{system_prompt}\n\nUser Question: {self.prompt}"
                    response = model.predict(full_prompt, temperature=0.2, max_output_tokens=1024)
                    response_text_raw = response.text
                else:
                    # Gemini Model
                    model = GenerativeModel(attempt['model'])
                    response = model.generate_content(system_prompt)
                    response_text_raw = response.text

                response_text = response_text_raw.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                
                ai_result = json.loads(response_text)
                # If success, break
                break
            except Exception as e:
                last_error = e
                error_msg = str(e)
                if "404" in error_msg:
                    _logger.warning(f"OdooGenBI: {attempt['model']} in {attempt['location']} failed (404).")
                    continue
                else:
                    # Non-404 error (e.g. 403 Permission, 500) -> Stop immediately
                    raise UserError(_("AI Generation failed (%s): %s") % (attempt['model'], error_msg))
                    
        if not ai_result:
             # All attempts failed
             raise UserError(_("All AI Models failed (404). Tested: User Config, 1.5-Flash, 1.5-Pro, 1.0-Pro in us-central1.\nLikely Cause: Service Account missing 'Vertex AI User' role or API disabled.\nLast Error: %s") % str(last_error))
            
        sql = ai_result.get('sql')
        chart_type = ai_result.get('type', 'bar')
        
        self.write({
            'sql_query': sql,
            'chart_type': chart_type,
        })
        
        # 3. Execute SQL
        try:
            query_job = client.query(sql)
            results = query_job.result()
            
            labels = []
            data = []
            
            labels_col = ai_result.get('labels_col')
            data_col = ai_result.get('data_col')
            
            # Auto-detect columns if not provided or wrong
            if not labels_col or not data_col:
                # Simple fallback: first string/date as label, first number as data
                # This is heuristic and might be improved
                pass

            for row in results:
                # Dynamic access
                labels.append(row[labels_col])
                data.append(row[data_col])
            
            chart_js_data = {
                'labels': labels,
                'datasets': [{
                    'label': self.prompt,
                    'data': data,
                    # Colors can be handled in frontend or here
                }]
            }
            
            self.chart_data = json.dumps(chart_js_data)
            
        except Exception as e:
            raise UserError(_("Query Execution failed: %s. SQL: %s") % (str(e), sql))
            
        return True

    @api.model
    def action_generate_preview(self, prompt):
        """Generate a chart preview without saving."""
        # Create a temporary instance in memory is hard in Odoo without creating a record.
        # So we will create a record and strictly return the data. User can 'save' by keeping it,
        # otherwise we might need a cleanup cron or just let user discard.
        # BETTER: Just run the logic without a record 'self'.
        
        client, credentials = self.env['bi.dashboard.item'].new({})._get_bq_client()
        dataset_id = self.env['ir.config_parameter'].sudo().get_param('odoo_gen_bi.bq_dataset_id', 'odoo_bi')
        
        # 1. Get Schema
        schema_summary = self.new({})._get_schema_summary(client, dataset_id)

        # 2. Call Gemini
        config = self.env['ir.config_parameter'].sudo()
        user_location = config.get_param('odoo_gen_bi.gcp_location', 'us-central1')
        user_model_name = config.get_param('odoo_gen_bi.ai_model_name', 'gemini-1.5-flash')
        
        _logger.info(f"OdooGenBI Preview: Project: {client.project}, Location: {user_location}")
        if hasattr(credentials, 'service_account_email'):
             _logger.info(f"OdooGenBI Preview: Service Account: {credentials.service_account_email}")
        
        # --- DIAGNOSTIC: List Models ---
        try:
             import google.generativeai as genai 
             # Note: vertexai.init was called? No, we need to call it first to set scope or use lower level api
             # But 'vertexai' sdk doesn't have a simple list_models that mirrors 'gcloud ai models list' easily without specific clients.
             # We will try a simple touch test.
             pass
        except:
             pass
        
        system_prompt = f"""
        You are a BigQuery SQL expert. The user wants to analyze their Odoo data.
        Dataset ID: `{dataset_id}`.
        Project ID: `{client.project}`.
        
        Schema available:
        {schema_summary}
        
        User Question: "{prompt}"
        
        Instructions:
        1. Write a Standard SQL query to answer the question.
        2. Use fully qualified table names: `{client.project}.{dataset_id}.table_name`.
        3. Determine the best chart type (bar, line, pie).
        4. Identify columns for labels (X-axis) and data (Y-axis).
        
        Return ONLY a JSON object with this format:
        {{
            "sql": "SELECT ...",
            "type": "bar",
            "labels_col": "column_name_for_labels",
            "data_col": "column_name_for_values"
        }}
        Do not use markdown formatting.
        """
             
        attempts = [
            {'model': user_model_name, 'location': user_location},
            {'model': 'gemini-2.5-flash', 'location': 'us-central1'},
            {'model': 'gemini-2.0-flash-001', 'location': 'us-central1'},
            {'model': 'gemini-1.5-flash', 'location': 'us-central1'},
            {'model': 'gemini-1.5-pro', 'location': 'us-central1'},
            {'model': 'gemini-1.0-pro', 'location': 'us-central1'},
            {'model': 'gemini-pro', 'location': 'us-central1'},
            {'model': 'text-bison', 'location': 'us-central1'},
        ]
        
        ai_result = None
        last_error = None
        
        for attempt in attempts:
            try:
                vertexai.init(project=client.project, location=attempt['location'], credentials=credentials)
                
                response_text_raw = ""

                if 'bison' in attempt['model']:
                    model = TextGenerationModel.from_pretrained(attempt['model'])
                    # Simplify prompt for PaLM
                    full_prompt = f"{system_prompt}\n\nUser Question: {prompt}"
                    response = model.predict(full_prompt, temperature=0.2, max_output_tokens=1024)
                    response_text_raw = response.text
                else:
                    model = GenerativeModel(attempt['model'])
                    response = model.generate_content(system_prompt)
                    response_text_raw = response.text

                text = response_text_raw.replace("```json", "").replace("```", "").strip()
                ai_result = json.loads(text)
                break
            except Exception as e:
                last_error = e
                error_msg = str(e)
                if "404" in error_msg:
                    _logger.warning(f"OdooGenBI: {attempt['model']} in {attempt['location']} failed (404).")
                    continue
                else:
                     raise UserError(_("AI Generation failed (%s): %s") % (attempt['model'], error_msg))
                     
        if not ai_result:
             raise UserError(_("All AI Models failed (404). Tested: User Config, 1.5-Flash, 1.5-Pro, 1.0-Pro in us-central1.\nLikely Cause: Service Account missing 'Vertex AI User' role or API disabled.\nLast Error: %s") % str(last_error))
            
        sql = ai_result.get('sql')
        chart_type = ai_result.get('type', 'bar')
        
        # 3. Execute SQL
        try:
            query_job = client.query(sql)
            results = query_job.result()
            
            warning_msg = False
            if results.total_rows == 0:
                import re
                # Simple regex to find table names (e.g. project_id.dataset.table)
                # Matches FROM `abc` or JOIN `abc`
                table_pattern = r"(?:FROM|JOIN)\s+`?([\w.-]+)`?"
                tables = re.findall(table_pattern, sql, re.IGNORECASE)
                unsynced = []
                for table_ref in tables:
                     try:
                         # table_ref might be just "table", need full path if not provided?
                         # Usually AI provides full path project.dataset.table
                         # If not, we might fail to find it, which is also a hint.
                         table = client.get_table(table_ref)
                         if table.num_rows == 0:
                             unsynced.append(table_ref)
                     except Exception:
                         unsynced.append(table_ref + " (Missing)")
                
                if unsynced:
                    warning_msg = _("Chart is empty. Check synchronization for: %s") % ", ".join(unsynced)

            labels = []
            data = []
            
            labels_col = ai_result.get('labels_col')
            data_col = ai_result.get('data_col')
            
            for row in results:
                labels.append(row.get(labels_col)) # .get safe access
                data.append(row.get(data_col))
            
            chart_js_data = {
                'labels': labels,
                'datasets': [{
                    'label': prompt,
                    'data': data,
                }]
            }
            
            return {
                'sql': sql,
                'chart_type': chart_type,
                'chart_data': json.dumps(chart_js_data),
                'warning': warning_msg
            }
            
        except Exception as e:
            raise UserError(_("Query Execution failed: %s. SQL: %s") % (str(e), sql))
