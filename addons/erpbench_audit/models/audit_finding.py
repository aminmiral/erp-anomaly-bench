from odoo import api, fields, models

PAID_STATES = ("paid", "in_payment", "partial")


class AuditFinding(models.Model):
    _name = "audit.finding"
    _description = "Audit Finding"
    _order = "severity desc, id desc"

    name = fields.Char(required=True)
    finding_type = fields.Selection([
        ("duplicate_invoice", "Duplicate Invoice"),
        ("price_overbill", "Bill Exceeds PO"),
        ("skipped_receipt", "Paid Without Receipt"),
    ], required=True)
    severity = fields.Selection(
        [("1", "Low"), ("2", "Medium"), ("3", "High")], default="2")
    po_id = fields.Many2one("purchase.order", string="Purchase Order")
    move_id = fields.Many2one("account.move", string="Vendor Bill")
    amount_expected = fields.Float()
    amount_found = fields.Float()
    note = fields.Text()

    @api.model
    def action_scan(self, _selected_ids=None):
        """Full rescan of all posted vendor bills / confirmed POs.

        The list-header button passes the current selection as an argument;
        the scan is always global, so it is accepted and ignored.

        v0 recomputes from scratch on each run; incremental scanning and an
        ir.cron schedule are follow-ups.
        """
        self.search([]).unlink()
        bills = self.env["account.move"].search([
            ("move_type", "=", "in_invoice"), ("state", "=", "posted")])
        pos = self.env["purchase.order"].search([
            ("state", "in", ("purchase", "done"))])
        po_by_name = {po.name: po for po in pos}
        findings = []

        # Rule 1: >1 posted bill referencing the same PO for the same vendor.
        by_ref = {}
        for bill in bills.filtered("ref"):
            by_ref.setdefault((bill.partner_id.id, bill.ref), []).append(bill)
        duplicated = set()
        for (_, ref), group in by_ref.items():
            for bill in group[1:]:
                duplicated.add(bill.id)
                findings.append({
                    "name": f"Duplicate bill {bill.name} for {ref}",
                    "finding_type": "duplicate_invoice",
                    "severity": "3",
                    "po_id": po_by_name[ref].id if ref in po_by_name else False,
                    "move_id": bill.id,
                    "amount_found": bill.amount_total,
                    "note": f"{len(group)} posted bills reference {ref}; "
                            f"first was {group[0].name}.",
                })

        # Rule 2: single bill exceeding its PO total beyond tolerance.
        for bill in bills.filtered("ref"):
            po = po_by_name.get(bill.ref)
            if po and bill.id not in duplicated \
                    and bill.amount_total > po.amount_total * 1.02:
                findings.append({
                    "name": f"Bill {bill.name} exceeds PO {po.name}",
                    "finding_type": "price_overbill",
                    "severity": "2",
                    "po_id": po.id,
                    "move_id": bill.id,
                    "amount_expected": po.amount_total,
                    "amount_found": bill.amount_total,
                    "note": f"Billed {bill.amount_total:.2f} vs approved "
                            f"{po.amount_total:.2f}.",
                })

        # Rule 3: bill paid while no receipt for the PO is done.
        for po in pos:
            if not po.picking_ids or any(p.state == "done" for p in po.picking_ids):
                continue
            paid = [b for b in bills
                    if b.ref == po.name and b.payment_state in PAID_STATES]
            for bill in paid:
                findings.append({
                    "name": f"{po.name} paid, goods never received",
                    "finding_type": "skipped_receipt",
                    "severity": "3",
                    "po_id": po.id,
                    "move_id": bill.id,
                    "amount_found": bill.amount_total,
                    "note": "Bill is paid but no receipt is validated "
                            "(3-way match violation).",
                })

        self.create(findings)
        return len(findings)
