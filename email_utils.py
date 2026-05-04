"""
Email utility module for GooCampus HR Portal.
Handles sending emails via Resend API with proper formatting and branding.
"""

import os
import logging
from typing import List, Optional

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Default sender
DEFAULT_SENDER = "GooCampus HR <info@goocampus.in>"

# GooCampus Branding Colors
BRAND_NAVY = "#1e3a5f"
BRAND_ORANGE = "#f97316"


def _get_resend_client():
    """
    Initialise and return the Resend module with the API key set.
    Returns None if the key is missing.
    """
    api_key = os.getenv('RESEND_API_KEY')
    if not api_key:
        logger.warning(
            "RESEND_API_KEY environment variable not set. "
            "Email sending is disabled."
        )
        return None

    try:
        import resend
        resend.api_key = api_key
        return resend
    except ImportError:
        logger.error("resend package not installed. Run: pip install resend")
        return None


def send_email(
    to_list: List[str],
    subject: str,
    html_body: str,
    from_address: str = DEFAULT_SENDER,
    cc_list: Optional[List[str]] = None
) -> bool:
    """
    Send an HTML email to a list of recipients via Resend API.

    Args:
        to_list: List of recipient email addresses.
        subject: Email subject line.
        html_body: HTML formatted email body.
        from_address: Sender address (default: GooCampus HR <info@goocampus.in>).
        cc_list: Optional list of CC recipient email addresses.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    resend = _get_resend_client()
    if resend is None:
        logger.warning(
            f"Skipping email send: Resend not configured. "
            f"Recipients: {to_list}"
        )
        return False

    if not to_list:
        logger.error("Cannot send email: recipient list is empty")
        return False

    try:
        params = {
            "from": from_address,
            "to": to_list,
            "subject": subject,
            "html": html_body,
        }
        if cc_list:
            params["cc"] = cc_list

        result = resend.Emails.send(params)

        logger.info(
            f"Email sent successfully via Resend to {len(to_list)} recipient(s). "
            f"Subject: {subject}, ID: {result.get('id', 'N/A')}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to send email via Resend: {str(e)}")
        return False


# ---------------------------------------------------------------------------
# Branded HTML helpers
# ---------------------------------------------------------------------------

def _get_email_header_html() -> str:
    """Generate GooCampus branded email header HTML."""
    return f"""
    <div style="background-color: {BRAND_NAVY}; padding: 20px; text-align: center; margin: 0;">
        <h1 style="color: white; margin: 0; font-family: Arial, sans-serif; font-size: 28px;">
            GooCampus HR Portal
        </h1>
        <p style="color: #e0e0e0; margin: 5px 0 0 0; font-family: Arial, sans-serif; font-size: 12px;">
            Human Resources Management System
        </p>
    </div>
    """


def _get_email_footer_html() -> str:
    """Generate GooCampus branded email footer HTML."""
    return f"""
    <div style="background-color: #f5f5f5; padding: 15px; text-align: center; margin-top: 30px; border-top: 3px solid {BRAND_ORANGE};">
        <p style="color: #666; font-family: Arial, sans-serif; font-size: 12px; margin: 0;">
            GooCampus HR Portal | Human Resources Management
        </p>
        <p style="color: #999; font-family: Arial, sans-serif; font-size: 11px; margin: 5px 0 0 0;">
            This is an automated message. Please do not reply to this email.
        </p>
    </div>
    """


# ---------------------------------------------------------------------------
# Pre-built email functions
# ---------------------------------------------------------------------------

def send_birthday_reminder(
    birthday_person_name: str,
    birthday_date: str,
    recipient_emails: List[str]
) -> bool:
    """Send a birthday reminder email to team members (1 day before)."""
    if not recipient_emails:
        logger.error("Cannot send birthday reminder: recipient list is empty")
        return False

    subject = f"Tomorrow is {birthday_person_name}'s Birthday!"

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">&#127881;</span> Birthday Reminder
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear Team,</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {BRAND_ORANGE}; padding: 15px; margin: 20px 0;">
                    <p style="font-size: 16px; margin: 0;">
                        <strong>{birthday_person_name}</strong> will be celebrating their birthday on
                        <strong>{birthday_date}</strong>!
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0;">
                    Please join us in wishing them a wonderful day filled with joy and happiness.
                    Feel free to reach out and share your birthday wishes!
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <p style="font-size: 24px; margin: 0;">&#127874; &#127882; &#127880;</p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    Best wishes,<br>
                    <strong style="color: {BRAND_NAVY};">GooCampus HR Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending birthday reminder for {birthday_person_name} "
        f"(Date: {birthday_date}) to {len(recipient_emails)} recipient(s)"
    )
    return send_email(recipient_emails, subject, html_body)


def send_anniversary_reminder(
    employee_name: str,
    years: int,
    anniversary_date: str,
    recipient_emails: List[str]
) -> bool:
    """Send a work anniversary reminder email to team members."""
    if not recipient_emails:
        logger.error("Cannot send anniversary reminder: recipient list is empty")
        return False

    anniversary_text = f"{years} year" if years == 1 else f"{years} years"
    subject = f"{employee_name} - {anniversary_text} Work Anniversary!"

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">&#11088;</span> Work Anniversary Milestone
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear Team,</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {BRAND_ORANGE}; padding: 15px; margin: 20px 0;">
                    <p style="font-size: 16px; margin: 0;">
                        We are pleased to celebrate that <strong>{employee_name}</strong> is completing
                        <strong>{anniversary_text}</strong> of service at GooCampus on
                        <strong>{anniversary_date}</strong>!
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0;">
                    {employee_name} has been a valuable member of our team, contributing to our success
                    and growth. Their dedication and hard work have not gone unnoticed.
                </p>
                <p style="font-size: 14px; margin: 20px 0;">
                    Let's take this opportunity to express our gratitude for their commitment and wish them
                    continued success in their career journey with us!
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <p style="font-size: 24px; margin: 0;">&#127881; &#127775; &#128079;</p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    With appreciation,<br>
                    <strong style="color: {BRAND_NAVY};">GooCampus HR Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending anniversary reminder for {employee_name} ({anniversary_text}) "
        f"to {len(recipient_emails)} recipient(s)"
    )
    return send_email(recipient_emails, subject, html_body)


def send_announcement_email(
    title: str,
    message: str,
    posted_by_name: str,
    recipient_emails: List[str]
) -> bool:
    """Send an announcement email to all recipients."""
    if not recipient_emails:
        logger.error("Cannot send announcement: recipient list is empty")
        return False

    subject = f"Announcement: {title}"
    formatted_message = message.replace('\n', '<br>')

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">&#128226;</span> {title}
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear Team,</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {BRAND_ORANGE}; padding: 20px; margin: 20px 0;">
                    <p style="font-size: 14px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">
                        {formatted_message}
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    Best regards,<br>
                    <strong style="color: {BRAND_NAVY};">{posted_by_name}</strong><br>
                    <span style="font-size: 12px;">GooCampus HR Team</span>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending announcement '{title}' from {posted_by_name} "
        f"to {len(recipient_emails)} recipient(s)"
    )
    return send_email(recipient_emails, subject, html_body)


def send_happy_birthday_email(
    birthday_person_name: str,
    birthday_person_email: str
) -> bool:
    """Send a warm happy birthday email directly to the birthday person."""
    if not birthday_person_email:
        logger.error("Cannot send happy birthday email: no email address")
        return False

    subject = f"Happy Birthday, {birthday_person_name}!"
    first_name = birthday_person_name.split()[0] if birthday_person_name else birthday_person_name

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <p style="font-size: 48px; margin: 0;">&#127874;&#127881;&#127880;</p>
                </div>
                <h2 style="color: {BRAND_NAVY}; text-align: center; margin-top: 0;">
                    Happy Birthday, <span style="color: {BRAND_ORANGE};">{first_name}!</span>
                </h2>
                <p style="font-size: 16px; margin: 20px 0; text-align: center;">
                    Dear <strong>{birthday_person_name}</strong>,
                </p>
                <div style="background: linear-gradient(135deg, #fff5eb, #fef3e6); border-left: 4px solid {BRAND_ORANGE}; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                    <p style="font-size: 15px; margin: 0; line-height: 1.8;">
                        On behalf of the entire <strong style="color: {BRAND_NAVY};">GooCampus</strong> family,
                        we wish you a very happy birthday!
                    </p>
                    <p style="font-size: 15px; margin: 12px 0 0 0; line-height: 1.8;">
                        Your hard work, dedication, and positive energy make our workplace better every day.
                        We are truly grateful to have you as part of our team.
                    </p>
                    <p style="font-size: 15px; margin: 12px 0 0 0; line-height: 1.8;">
                        May this special day bring you endless joy, good health, and all the happiness
                        you deserve. Here's to another wonderful year ahead!
                    </p>
                </div>
                <div style="text-align: center; margin: 30px 0;">
                    <p style="font-size: 36px; margin: 0;">&#127882; &#127873; &#127775; &#127880; &#127874;</p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666; text-align: center;">
                    With warm wishes from all of us,<br>
                    <strong style="color: {BRAND_NAVY};">The GooCampus Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending happy birthday email to {birthday_person_name} "
        f"({birthday_person_email})"
    )
    return send_email([birthday_person_email], subject, html_body)


def send_leave_status_email(
    employee_name: str,
    employee_email: str,
    leave_type: str,
    leave_date: str,
    status: str,
    actioned_by: str
) -> bool:
    """Send a leave approved/rejected email to the employee."""
    if not employee_email:
        logger.error("Cannot send leave status email: no email address")
        return False

    is_approved = status.lower() == 'approved'
    status_label = "Approved" if is_approved else "Rejected"
    status_color = "#22c55e" if is_approved else "#ef4444"
    status_icon = "&#9989;" if is_approved else "&#10060;"
    first_name = employee_name.split()[0] if employee_name else employee_name

    subject = f"Leave {status_label} — {leave_type} on {leave_date}"

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    {status_icon} Leave {status_label}
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear {first_name},</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {status_color}; padding: 15px; margin: 20px 0;">
                    <p style="font-size: 15px; margin: 0;">
                        Your <strong>{leave_type}</strong> leave on
                        <strong>{leave_date}</strong> has been
                        <strong style="color: {status_color};">{status_label.lower()}</strong>
                        by <strong>{actioned_by}</strong>.
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    You can view your leave history on the HR Portal.
                </p>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    Regards,<br>
                    <strong style="color: {BRAND_NAVY};">GooCampus HR Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending leave {status_label.lower()} email to {employee_name} "
        f"({employee_email})"
    )
    return send_email([employee_email], subject, html_body)


if __name__ == "__main__":
    logger.info("Email utilities module loaded successfully (Resend)")
