"""Thin connection wrapper around odoorpc plus master-data setup.

The database starts empty (--without-demo), so the driver creates its own
vendors and products once and reuses them across all simulated cases.
"""

from __future__ import annotations

import random

import odoorpc


class OdooClient:
    def __init__(self, host="localhost", port=8069, db="erpbench",
                 login="admin", password="admin"):
        self.odoo = odoorpc.ODOO(host, port=port)
        self.odoo.login(db, login, password)
        self.env = self.odoo.env

    # ---- master data -------------------------------------------------

    def ensure_vendors(self, names: list[str]) -> dict[str, int]:
        Partner = self.env["res.partner"]
        out = {}
        for name in names:
            ids = Partner.search([("name", "=", name)])
            out[name] = ids[0] if ids else Partner.create(
                {"name": name, "supplier_rank": 1}
            )
        return out

    def ensure_products(self, specs: list[tuple[str, float]]) -> dict[str, tuple[int, float]]:
        """specs: (name, cost). Storable products so receipts exist; billed on
        ordered quantities so the ERP permits billing before receipt (which is
        exactly what makes skipped-receipt fraud possible)."""
        Product = self.env["product.product"]
        out = {}
        for name, price in specs:
            ids = Product.search([("name", "=", name)])
            pid = ids[0] if ids else Product.create({
                "name": name,
                "detailed_type": "product",
                "purchase_method": "purchase",
                "standard_price": price,
                "list_price": price * 1.3,
            })
            out[name] = (pid, price)
        return out


def make_master_data(client: OdooClient, rng: random.Random,
                     n_vendors: int = 8, n_products: int = 15):
    vendors = client.ensure_vendors([f"Vendor {chr(65 + i)}" for i in range(n_vendors)])
    products = client.ensure_products([
        (f"Component {i:03d}", round(rng.uniform(5, 900), 2))
        for i in range(n_products)
    ])
    return vendors, products
