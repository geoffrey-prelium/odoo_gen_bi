{
    'name': 'Odoo Generative BI',
    'version': '1.0',
    'category': 'Business Intelligence',
    'summary': 'Generative BI with BigQuery and Vertex AI (Gemini)',
    'description': """
        Integrate Odoo with Google Cloud Platform for Generative Business Intelligence.
        - Sync Odoo models to BigQuery (BYOK)
        - Use Vertex AI (Gemini 1.5 Flash) for Text-to-SQL
        - Visualize results in a Chart.js Dashboard
    """,
    'author': 'Antigravity',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/bi_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_gen_bi/static/src/xml/dashboard.xml',
            'odoo_gen_bi/static/src/js/dashboard.js',
        ],
    },
    'external_dependencies': {
        'python': ['google.cloud.bigquery', 'google.cloud.aiplatform'],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
