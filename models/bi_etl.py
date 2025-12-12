# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import base64
import logging
import datetime

_logger = logging.getLogger(__name__)

try:
    from google.cloud import bigquery
    from google.oauth2 import service_account
except ImportError:
    bigquery = None
    service_account = None

class BiExportConfig(models.Model):
    _name = 'bi.export.config'
    _description = 'BI Export Configuration'

    name = fields.Char(string="Name", default="Default Configuration", required=True)
    model_ids = fields.Many2many('ir.model', string="Models to Sync", domain=[('transient', '=', False)], help="Select Odoo models to export to BigQuery.")
    last_sync_date = fields.Datetime(string="Last Sync", readonly=True)
    
    def _get_bq_client(self):
        """Helper to get BigQuery Client."""
        if not bigquery:
            raise UserError(_("Google Cloud BigQuery library is not installed. Please install 'google-cloud-bigquery'."))
            
        settings = self.env['res.config.settings'].get_values()
        # Note: res.config.settings.get_values() might return defaults or stored values. 
        # Better to access ir.config_parameter directly or use filtered logic.
        
        params = self.env['ir.config_parameter'].sudo()
        json_b64 = params.get_param('odoo_gen_bi.gcp_credentials_json')
        project_id = params.get_param('odoo_gen_bi.gcp_project_id')
        
        if not json_b64:
             raise UserError(_("GCP Credentials not found. Please configure them in Settings."))
        
        try:
            creds_data = json.loads(base64.b64decode(json_b64))
            credentials = service_account.Credentials.from_service_account_info(creds_data)
            return bigquery.Client(credentials=credentials, project=credentials.project_id)
        except Exception as e:
            raise UserError(_("Failed to create BigQuery Client: %s") % str(e))

    def _map_odoo_type_to_bq(self, field_type):
        """Map Odoo field types to BigQuery types."""
        mapping = {
            'char': 'STRING',
            'text': 'STRING',
            'html': 'STRING',
            'selection': 'STRING',
            'integer': 'INT64',
            'float': 'FLOAT64',
            'monetary': 'FLOAT64',
            'boolean': 'BOOL',
            'date': 'DATE',
            'datetime': 'TIMESTAMP',
            'many2one': 'INT64', 
        }
        return mapping.get(field_type, 'STRING')

    def action_sync_to_bq(self):
        """Main method to sync selected models to BigQuery."""
        client = self._get_bq_client()
        dataset_id = self.env['ir.config_parameter'].sudo().get_param('odoo_gen_bi.bq_dataset_id', 'odoo_bi')
        
        # Ensure Dataset exists
        dataset_ref = f"{client.project}.{dataset_id}"
        try:
            client.get_dataset(dataset_ref)
        except Exception:
            # Create if not exists
            dataset = bigquery.Dataset(dataset_ref)
            dataset.location = "US" # Or make configurable
            client.create_dataset(dataset)
            _logger.info(f"Created dataset {dataset_id}")

        for model in self.model_ids:
            self._sync_model(client, dataset_id, model)
        
        self.last_sync_date = fields.Datetime.now()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Sync completed successfully for %s models.') % len(self.model_ids),
                'type': 'success',
                'sticky': False,
            }
        }

    def _sync_model(self, client, dataset_id, model_record):
        """Sync a single model."""
        table_id = f"{client.project}.{dataset_id}.{model_record.model.replace('.', '_')}"
        
        Model = self.env[model_record.model]
        # Fetch all data (potentially heavy, fine for V1)
        records = Model.search([])
        if not records:
            _logger.info(f"No records for {model_record.model}, skipping.")
            return

        # Prepare Schema and Data
        schema = []
        rows = []
        
        # We only export stored fields
        valid_fields = {}
        for fname, field in Model._fields.items():
            if field.store and field.type in ('char', 'text', 'integer', 'float', 'boolean', 'date', 'datetime', 'selection', 'many2one', 'monetary'):
                 valid_fields[fname] = field
        
        # Build Schema
        for fname, field in valid_fields.items():
            bq_type = self._map_odoo_type_to_bq(field.type)
            schema.append(bigquery.SchemaField(fname, bq_type))

        # Build Rows
        for record in records:
            row = {}
            for fname, field in valid_fields.items():
                val = record[fname]
                
                # Handle types
                if field.type == 'many2one':
                    row[fname] = val.id if val else None
                elif field.type in ('date', 'datetime'):
                     # Odoo returns date/datetime objects or strings depending on context, usually objects in code
                     if val:
                         row[fname] = val.isoformat() if hasattr(val, 'isoformat') else val
                     else:
                         row[fname] = None
                else:
                    row[fname] = val
            rows.append(row)

        # Load Data
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )

        try:
            job = client.load_table_from_json(rows, table_id, job_config=job_config)
            job.result() # Wait for job to complete
            _logger.info(f"Loaded {len(rows)} rows into {table_id}")
        except Exception as e:
            _logger.error(f"Failed to load {model_record.model}: {e}")
            raise UserError(_("Failed to load %s: %s") % (model_record.model, str(e)))

    @api.model
    def run_scheduler(self):
        """Cron job entry point."""
        configs = self.search([])
        for config in configs:
            try:
                config.action_sync_to_bq()
                _logger.info(f"Cron: Successfully synced config {config.name}")
            except Exception as e:
                _logger.error(f"Cron: Failed to sync config {config.name}: {e}")

