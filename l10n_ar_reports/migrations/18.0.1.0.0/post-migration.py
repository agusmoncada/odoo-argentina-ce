# Migracion 16.0 -> 18.0 del Libro IVA Digital.
#
# account_vat_ledger (registros, TXT guardados en REGINFO_CV_*, adjuntos y chatter)
# no cambia de estructura: el modulo conserva nombre, modelo y tabla.
#
# Lo unico que cambia es account_move.l10n_ar_currency_rate: en 16 lo definia l10n_ar
# y en 18 lo define este modulo. Como el campo sigue existiendo, la columna y sus valores
# historicos se conservan. Aca solo completamos los comprobantes que no lo tengan
# (p.ej. contabilizados durante el paso por 17 o si la columna no existia).
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'account_move' AND column_name = 'l10n_ar_currency_rate'
        """
    )
    if not cr.fetchone():
        cr.execute("ALTER TABLE account_move ADD COLUMN l10n_ar_currency_rate double precision")
    cr.execute(
        """
        UPDATE account_move am
           SET l10n_ar_currency_rate = CASE
                   WHEN am.currency_id = rc.currency_id THEN 1.0
                   WHEN COALESCE(am.invoice_currency_rate, 0) <> 0 THEN round((1.0 / am.invoice_currency_rate)::numeric, 6)
                   ELSE NULL END
          FROM res_company rc
         WHERE rc.id = am.company_id
           AND am.l10n_latam_document_type_id IS NOT NULL
           AND am.state = 'posted'
           AND COALESCE(am.l10n_ar_currency_rate, 0) = 0
        """
    )
    _logger.info("l10n_ar_reports: l10n_ar_currency_rate completado en %s comprobantes", cr.rowcount)
    cr.execute("SELECT state, count(*) FROM account_vat_ledger GROUP BY state ORDER BY state")
    _logger.info("l10n_ar_reports: libros IVA conservados %s", cr.fetchall())
