"""State for two invoice reads in one conversation, without cached invoice values."""
from dataclasses import dataclass, field


@dataclass
class InvoiceRead:
    company_id: str | None = None
    invoice_no: str | None = None
    status: str = "WAITING"

    @property
    def key(self):
        if self.company_id and self.invoice_no:
            return {"company_id": self.company_id, "invoice_no": self.invoice_no}
        return None


@dataclass
class InvoiceQueryChain:
    request: str
    first: InvoiceRead
    second: InvoiceRead = field(default_factory=InvoiceRead)

    def item(self, position):
        return self.first if position == "first" else self.second

    def company_for(self, position):
        return self.item(position).company_id or self.first.company_id

    def next_position(self):
        for position in ("first", "second"):
            if self.item(position).status not in {"SUCCESS", "CANCELLED"}:
                return position
        return None

    def pending(self, actor, workbook):
        position = self.next_position()
        if position is None:
            return None
        company = self.company_for(position)
        missing = "company_id" if not company else "first_invoice_no" if position == "first" else "invoice_no"
        return {"request": self.request, "scope": {"company_id": [company]} if company else {},
                "missing_fields": (missing,), "actor": actor, "workbook": str(workbook),
                "invoice_followup": True}
