{
    "name": "ERP Audit Findings",
    "summary": "Rule-based fraud/anomaly flags on procure-to-pay documents",
    "version": "17.0.0.1.0",
    "category": "Accounting",
    "license": "LGPL-3",
    "depends": ["purchase", "stock", "account"],
    "data": [
        "security/ir.model.access.csv",
        "views/audit_finding_views.xml",
    ],
    "application": True,
}
