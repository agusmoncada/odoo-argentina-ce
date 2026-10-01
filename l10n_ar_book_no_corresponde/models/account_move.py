from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _l10n_ar_vat_book_get_amounts(self, company_currency=False):
        """Suma las lineas con 'IVA No Corresponde' (codigo AFIP 0) al importe de
        conceptos que NO integran el precio neto gravado (Campo 10 del TXT).

        l10n_ar solo vuelca a un campo del Libro IVA Digital los codigos de IVA
        '1' (No Gravado -> Campo 10) y '2' (Exento -> Campo 11). El codigo '0'
        ('No Corresponde'), que llevan las FACTURAS C de proveedores
        monotributistas, no va a NINGUN campo y ARCA rechaza el comprobante con
        "El Importe Total no coincide con la suma de los demas montos".
        Tampoco genera fila de alicuota, asi que no se cuenta dos veces.

        Criterio del estudio contable (2026-08-14): informarlas como NO GRAVADO.

        En 16 este modulo extendia l10n_ar._l10n_ar_get_amounts (afectando tambien
        a la factura electronica); en 18 extiende solo el calculo del libro.
        """
        res = super()._l10n_ar_vat_book_get_amounts(company_currency=company_currency)
        self.ensure_one()
        amount_field = "balance" if company_currency else "amount_currency"
        sign = self._l10n_ar_vat_book_sign()
        no_corresponde = self.invoice_line_ids.filtered(
            lambda line: line.tax_ids.filtered(lambda t: t.tax_group_id.l10n_ar_vat_afip_code == "0")
        )
        if no_corresponde:
            res["vat_untaxed_base_amount"] = res.get("vat_untaxed_base_amount", 0.0) + sign * sum(
                no_corresponde.mapped(amount_field)
            )
        return res
