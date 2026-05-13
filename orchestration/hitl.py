"""Human-in-the-loop approval logic."""

from schemas.reports import ReportDepth, ReportType


def requires_approval(report_type: ReportType, depth: ReportDepth) -> bool:
    """Return whether a report requires human approval before export."""
    return report_type in {ReportType.INVESTMENT_MEMO, ReportType.POLICY_BRIEF} or depth == ReportDepth.DEEP
