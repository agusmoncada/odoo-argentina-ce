##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    # En 16 este campo lo definia l10n_ar (core) y Odoo 18 lo elimino a favor de
    # invoice_currency_rate (que va de moneda compania a moneda documento, es decir
    # la inversa). Lo mantenemos aca para conservar el tipo de cambio historico con
    # el que se contabilizo y se informo cada comprobante (campo 18 del TXT).
    l10n_ar_currency_rate = fields.Float(
        string="AFIP Currency Rate",
        copy=False,
        readonly=True,
        digits=(16, 6),
        help="Tipo de cambio (pesos por unidad de moneda del comprobante) informado en el Libro IVA Digital.",
    )

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        posted.filtered(
            lambda x: x.company_id.account_fiscal_country_id.code == "AR" and x.l10n_latam_use_documents
        )._l10n_ar_vat_book_set_currency_rate()
        return posted

    def _l10n_ar_vat_book_set_currency_rate(self):
        """Misma regla que l10n_ar 16 (_set_afip_rate): 1 si es moneda de la compania; si no,
        pesos por unidad de moneda del comprobante, sin pisar un valor ya fijado."""
        for rec in self:
            if rec.company_id.currency_id == rec.currency_id:
                rec.l10n_ar_currency_rate = 1.0
            elif not rec.l10n_ar_currency_rate:
                rec.l10n_ar_currency_rate = rec._l10n_ar_vat_book_fallback_rate()

    def _l10n_ar_vat_book_fallback_rate(self):
        self.ensure_one()
        if self.company_id.currency_id == self.currency_id:
            return 1.0
        # el TXT informa el tipo de cambio con 6 decimales: redondeamos para no truncar
        # 1449.9999999 a 1449.999999 al formatear
        if self.invoice_currency_rate:
            return round(1.0 / self.invoice_currency_rate, 6)
        return round(
            self.currency_id._convert(
                1.0,
                self.company_id.currency_id,
                self.company_id,
                self.date or fields.Date.context_today(self),
                round=False,
            ),
            6,
        )

    def _l10n_ar_vat_book_currency_rate(self):
        self.ensure_one()
        return self.l10n_ar_currency_rate or self._l10n_ar_vat_book_fallback_rate()

    def _l10n_ar_vat_book_sign(self):
        """Signo de l10n_ar 16 (_l10n_ar_get_amounts)."""
        sign = -1 if self.is_inbound() else 1
        if (
            self.move_type in ("out_refund", "in_refund")
            and self.l10n_latam_document_type_id.code in self._get_l10n_ar_codes_used_for_inv_and_ref()
        ):
            sign = -sign
        return sign

    def _l10n_ar_vat_book_profits_tax_group(self):
        self.ensure_one()
        return (
            self.env["account.chart.template"]
            .with_company(self.company_id)
            .ref("tax_group_percepcion_ganancias", raise_if_not_found=False)
            or self.env["account.tax.group"]
        )

    def _l10n_ar_vat_book_get_amounts(self, company_currency=False):
        """Importes del Libro IVA Digital calculados exactamente como _l10n_ar_get_amounts de
        l10n_ar 16.0 (sobre los apuntes contables). En 18 el metodo del core cambio de firma y de
        criterio (base_lines, siempre moneda del documento), asi que el libro usa este calculo propio
        para que los TXT sean identicos a los generados en 16. Punto de extension para ajustes del
        libro (p.ej. l10n_ar_book_no_corresponde)."""
        self.ensure_one()
        amount_field = company_currency and "balance" or "amount_currency"
        sign = self._l10n_ar_vat_book_sign()

        tax_lines = self.line_ids.filtered("tax_line_id")
        vat_taxes = tax_lines.filtered(lambda r: r.tax_line_id.tax_group_id.l10n_ar_vat_afip_code)

        vat_taxable = self.env["account.move.line"]
        for line in self.invoice_line_ids:
            if any(
                tax.tax_group_id.l10n_ar_vat_afip_code and tax.tax_group_id.l10n_ar_vat_afip_code not in ["0", "1", "2"]
                for tax in line.tax_ids
            ):
                vat_taxable |= line

        profits_tax_group = self._l10n_ar_vat_book_profits_tax_group()

        def _sum(lines):
            return sign * sum(lines.mapped(amount_field))

        def _by_tribute(code):
            return tax_lines.filtered(lambda r: r.tax_line_id.tax_group_id.l10n_ar_tribute_afip_code == code)

        return {
            "vat_amount": _sum(vat_taxes),
            # For invoices of letter C should not pass VAT
            "vat_taxable_amount": _sum(vat_taxable)
            if self.l10n_latam_document_type_id.l10n_ar_letter != "C"
            else self.amount_untaxed,
            "vat_exempt_base_amount": _sum(
                self.invoice_line_ids.filtered(
                    lambda x: x.tax_ids.filtered(lambda y: y.tax_group_id.l10n_ar_vat_afip_code == "2")
                )
            ),
            "vat_untaxed_base_amount": _sum(
                self.invoice_line_ids.filtered(
                    lambda x: x.tax_ids.filtered(lambda y: y.tax_group_id.l10n_ar_vat_afip_code == "1")
                )
            ),
            "not_vat_taxes_amount": _sum(tax_lines - vat_taxes),
            "iibb_perc_amount": _sum(_by_tribute("07")),
            "mun_perc_amount": _sum(_by_tribute("08")),
            "intern_tax_amount": _sum(_by_tribute("04")),
            "other_taxes_amount": _sum(_by_tribute("99")),
            "profits_perc_amount": _sum(
                tax_lines.filtered(lambda r: profits_tax_group and r.tax_line_id.tax_group_id == profits_tax_group)
            ),
            "vat_perc_amount": _sum(_by_tribute("06")),
            "other_perc_amount": _sum(
                tax_lines.filtered(
                    lambda r: (
                        r.tax_line_id.tax_group_id.l10n_ar_tribute_afip_code == "09"
                        and r.tax_line_id.tax_group_id != profits_tax_group
                    )
                )
            ),
        }

    def _l10n_ar_vat_book_get_vat(self):
        """Alicuotas de IVA calculadas como _get_vat de l10n_ar 16.0 (moneda del documento)."""
        self.ensure_one()
        sign = (
            -1
            if self.move_type in ("out_refund", "in_refund")
            and self.l10n_latam_document_type_id.code in self._get_l10n_ar_codes_used_for_inv_and_ref()
            else 1
        )

        res = []
        vat_taxable = self.env["account.move.line"]
        # get all invoice lines that are vat taxable
        for line in self.line_ids:
            if (
                any(
                    tax.tax_group_id.l10n_ar_vat_afip_code
                    and tax.tax_group_id.l10n_ar_vat_afip_code not in ["0", "1", "2"]
                    for tax in line.tax_line_id
                )
                and line["amount_currency"]
            ):
                vat_taxable |= line
        for tax_group in vat_taxable.mapped("tax_group_id"):
            base_imp = sum(
                self.invoice_line_ids.filtered(
                    lambda x: x.tax_ids.filtered(
                        lambda y: y.tax_group_id.l10n_ar_vat_afip_code == tax_group.l10n_ar_vat_afip_code
                    )
                ).mapped("price_subtotal")
            )
            imp = abs(
                sum(
                    vat_taxable.filtered(
                        lambda x: x.tax_group_id.l10n_ar_vat_afip_code == tax_group.l10n_ar_vat_afip_code
                    ).mapped("amount_currency")
                )
            )
            res += [{"Id": tax_group.l10n_ar_vat_afip_code, "BaseImp": sign * base_imp, "Importe": sign * imp}]

        # Report vat 0%
        vat_base_0 = sum(
            self.invoice_line_ids.filtered(
                lambda x: x.tax_ids.filtered(lambda y: y.tax_group_id.l10n_ar_vat_afip_code == "3")
            ).mapped("price_subtotal")
        )
        if vat_base_0:
            res += [{"Id": "3", "BaseImp": vat_base_0, "Importe": 0.0}]

        return res
