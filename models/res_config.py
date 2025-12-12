# -*- coding: utf-8 -*-
import json
import base64
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bi_gcp_credentials_json = fields.Binary(
        string="GCP Service Account JSON",
        help="Upload your Google Cloud Service Account JSON key here.",
        attachment=False, 
    )
    bi_bq_dataset_id = fields.Char(
        string="BigQuery Dataset ID",
        default="odoo_bi",
        config_parameter='odoo_gen_bi.bq_dataset_id',
        help="Name of the dataset in BigQuery where tables will be created."
    )
    bi_gcp_project_id = fields.Char(
        string="GCP Project ID",
        config_parameter='odoo_gen_bi.gcp_project_id',
        help="Project ID from Google Cloud Console."
    )
    bi_gcp_location = fields.Selection([
        ('us-central1', 'us-central1 (Iowa)'),
        ('us-east4', 'us-east4 (N. Virginia)'),
        ('us-west1', 'us-west1 (Oregon)'),
        ('europe-west1', 'europe-west1 (Belgium)'),
        ('europe-west2', 'europe-west2 (London)'),
        ('europe-west3', 'europe-west3 (Frankfurt)'),
        ('europe-west4', 'europe-west4 (Netherlands)'),
        ('asia-northeast1', 'asia-northeast1 (Tokyo)'),
        ('asia-southeast1', 'asia-southeast1 (Singapore)'),
    ], string="GCP Location",
        default="us-central1",
        config_parameter='odoo_gen_bi.gcp_location',
        help="Vertex AI Location."
    )
    bi_ai_model_name = fields.Selection([
        ('gemini-2.5-flash', 'Gemini 2.5 Flash (Recommended)'),
        ('gemini-2.5-pro', 'Gemini 2.5 Pro'),
        ('gemini-2.0-flash-001', 'Gemini 2.0 Flash'),
        ('gemini-1.5-flash', 'Gemini 1.5 Flash'),
        ('gemini-1.5-pro', 'Gemini 1.5 Pro'),
        ('gemini-1.0-pro', 'Gemini 1.0 Pro'),
        ('gemini-pro', 'Gemini Pro (Legacy)'),
    ], string="AI Model Name",
        default="gemini-2.5-flash",
        config_parameter='odoo_gen_bi.ai_model_name',
        help="Model ID to use.")

    # Cron Config
    bi_auto_sync = fields.Boolean(string="Auto Sync to BigQuery")
    bi_sync_interval_number = fields.Integer(string="Interval Number", default=1)
    bi_sync_interval_type = fields.Selection([
        ('minutes', 'Minutes'),
        ('hours', 'Hours'),
        ('days', 'Days'),
        ('weeks', 'Weeks')
    ], string="Interval In", default='days')

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        # Manually save the binary field
        param = self.env['ir.config_parameter'].sudo()
        if self.bi_gcp_credentials_json:
             # We store the base64 string directly in the parameter
             param.set_param('odoo_gen_bi.gcp_credentials_json', self.bi_gcp_credentials_json.decode('utf-8'))
        
        # Update Cron
        # We want to know if this fails, so we let it raise if not found
        cron = self.env.ref('odoo_gen_bi.ir_cron_bi_sync')
        cron.write({
            'active': self.bi_auto_sync,
            'interval_number': self.bi_sync_interval_number,
            'interval_type': self.bi_sync_interval_type,
        })
    
    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        param = self.env['ir.config_parameter'].sudo()
        json_b64 = param.get_param('odoo_gen_bi.gcp_credentials_json', False)
        # Add it to the result dict if it exists
        if json_b64:
             res.update(
                 bi_gcp_credentials_json=json_b64.encode('utf-8'),
             )
        # For getting values, we can be softer, but better to be consistent
        try:
            cron = self.env.ref('odoo_gen_bi.ir_cron_bi_sync')
            res.update({
                'bi_auto_sync': cron.active,
                'bi_sync_interval_number': cron.interval_number,
                'bi_sync_interval_type': cron.interval_type,
            })
        except ValueError:
            # Cron not found yet
            res.update({'bi_auto_sync': False})
            
        return res

    @api.onchange('bi_gcp_credentials_json')
    def _onchange_gcp_credentials(self):
        """Automatically extract project_id from the uploaded JSON file."""
        if self.bi_gcp_credentials_json:
            try:
                decoded = base64.b64decode(self.bi_gcp_credentials_json)
                data = json.loads(decoded)
                if 'project_id' in data:
                    self.bi_gcp_project_id = data['project_id']
                else:
                    _logger.warning("No 'project_id' found in the GCP JSON file.")
            except Exception as e:
                _logger.error(f"Error parsing GCP Credentials: {e}")
                # Note: We avoid raising UserError in onchange to keep UI smooth, 
                # but valid credentials are required for the module to work.
