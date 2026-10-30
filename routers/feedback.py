import logging
import os
import smtplib
from email import policy
from email.message import EmailMessage
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from auth import get_current_user

router = APIRouter(prefix="/api", tags=["feedback"])
logger = logging.getLogger(__name__)


class FeedbackIn(BaseModel):
    what_tried: str
    what_happened: str
    page_url: Optional[str] = None
    browser: Optional[str] = None


@router.post("/feedback", status_code=204)
def submit_feedback(data: FeedbackIn, request: Request, _=Depends(get_current_user)):
    tenant = request.state.tenant
    try:
        _create_github_issue(data, tenant)
    except Exception:
        logger.exception("GitHub issue creation failed")
    try:
        _send_email(data, tenant)
    except Exception:
        logger.exception("Feedback email failed")


def _create_github_issue(data: FeedbackIn, tenant) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPO")
    if not token or not repo_name:
        logger.warning("GITHUB_TOKEN or GITHUB_REPO not set — skipping GitHub issue")
        return

    from github import Github, GithubException

    g = Github(token)
    repo = g.get_repo(repo_name)

    title = f"[Feedback] {tenant.slug}: {data.what_tried[:60]}"
    body = (
        f"**Tenant:** {tenant.slug} ({tenant.name})\n"
        f"**Page:** {data.page_url or 'unknown'}\n"
        f"**Browser:** {data.browser or 'unknown'}\n\n"
        f"### What were you trying to do?\n{data.what_tried}\n\n"
        f"### What happened instead?\n{data.what_happened}"
    )

    try:
        issue = repo.create_issue(title=title, body=body, labels=["feedback"])
    except GithubException:
        # Label may not exist — retry without label
        issue = repo.create_issue(title=title, body=body)

    logger.info("Created GitHub issue #%s for tenant %s", issue.number, tenant.slug)


def _send_email(data: FeedbackIn, tenant) -> None:
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not smtp_user:
        logger.warning("SMTP_USER not set — skipping feedback email")
        return

    smtp_pass = "".join(c for c in smtp_pass if 32 < ord(c) < 127)

    subject = f"[Waypoint Feedback] {tenant.slug}: {data.what_tried[:60]}"
    body = (
        f"<p><strong>Tenant:</strong> {tenant.slug} ({tenant.name})</p>"
        f"<p><strong>Page:</strong> {data.page_url or 'unknown'}</p>"
        f"<p><strong>Browser:</strong> {data.browser or 'unknown'}</p>"
        f"<h3>What were you trying to do?</h3><p>{data.what_tried}</p>"
        f"<h3>What happened instead?</h3><p>{data.what_happened}</p>"
    )

    msg = EmailMessage(policy=policy.SMTP)
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = smtp_user
    msg.set_content(body, subtype="html", charset="utf-8")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
        srv.starttls()
        srv.login(smtp_user, smtp_pass)
        srv.send_message(msg)

    logger.info("Feedback email sent for tenant %s", tenant.slug)
