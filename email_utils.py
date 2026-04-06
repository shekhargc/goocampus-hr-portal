"""
Email utility module for GooCampus HR Portal.
Handles sending emails via Gmail SMTP with proper formatting and branding.
"""

import smtplib
import os
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Gmail SMTP Configuration
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587

# Default sender email
DEFAULT_GMAIL_USER = "info@goocampus.in"

# GooCampus Branding Colors
BRAND_NAVY = "#1e3a5f"
BRAND_ORANGE = "#f97316"


def get_gmail_credentials() -> tuple[Optional[str], Optional[str]]:
    """
    Retrieve Gmail credentials from environment variables.

    Returns:
        Tuple of (gmail_user, gmail_app_password) or (None, None) if not configured.
    """
    gmail_user = os.getenv('GMAIL_USER', DEFAULT_GMAIL_USER)
    gmail_app_password = os.getenv('GMAIL_APP_PASSWORD')

    if not gmail_app_password:
        logger.warning(
            "GMAIL_APP_PASSWORD environment variable not set. "
            "Email sending is disabled."
        )
        return None, None

    return gmail_user, gmail_app_password


def send_email(
    to_list: List[str],
    subject: str,
    html_body: str
) -> bool:
    """
    Send an HTML email to a list of recipients via Gmail SMTP.

    Args:
        to_list: List of recipient email addresses.
        subject: Email subject line.
        html_body: HTML formatted email body.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    gmail_user, gmail_app_password = get_gmail_credentials()

    if not gmail_user or not gmail_app_password:
        logger.warning(
            f"Skipping email send: Gmail credentials not configured. "
            f"Recipients: {to_list}"
        )
        return False

    if not to_list:
        logger.error("Cannot send email: recipient list is empty")
        return False

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = gmail_user
        msg['To'] = ', '.join(to_list)

        # Attach HTML body
        msg.attach(MIMEText(html_body, 'html'))

        # Send via Gmail SMTP
        with smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_list, msg.as_string())

        logger.info(
            f"Email sent successfully to {len(to_list)} recipient(s). "
            f"Subject: {subject}"
        )
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(
            f"SMTP authentication failed. Check GMAIL_USER and GMAIL_APP_PASSWORD. "
            f"Error: {str(e)}"
        )
        return False

    except smtplib.SMTPException as e:
        logger.error(f"SMTP error occurred while sending email: {str(e)}")
        return False

    except Exception as e:
        logger.error(f"Unexpected error while sending email: {str(e)}")
        return False


def _get_email_header_html() -> str:
    """
    Generate GooCampus branded email header HTML.

    Returns:
        HTML string for the email header.
    """
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
    """
    Generate GooCampus branded email footer HTML.

    Returns:
        HTML string for the email footer.
    """
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


def send_birthday_reminder(
    birthday_person_name: str,
    birthday_date: str,
    recipient_emails: List[str]
) -> bool:
    """
    Send a birthday reminder email to team members.
    Sent 1 day before the birthday.

    Args:
        birthday_person_name: Name of the person having the birthday.
        birthday_date: Birthday date (format: YYYY-MM-DD or any readable format).
        recipient_emails: List of team member emails to receive the reminder.

    Returns:
        True if email was sent successfully, False otherwise.
    """
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
                    <span style="color: {BRAND_ORANGE};">🎉</span> Birthday Reminder
                </h2>

                <p style="font-size: 16px; margin: 20px 0;">
                    Dear Team,
                </p>

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
                    <p style="font-size: 24px; margin: 0;">
                        🎂 🎊 🎈
                    </p>
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
    """
    Send a work anniversary reminder email to team members.

    Args:
        employee_name: Name of the employee.
        years: Number of years of service.
        anniversary_date: Anniversary date (format: YYYY-MM-DD or any readable format).
        recipient_emails: List of team member emails to receive the reminder.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    if not recipient_emails:
        logger.error("Cannot send anniversary reminder: recipient list is empty")
        return False

    subject = f"{employee_name} - {years} Year{'s' if years != 1 else ''} Work Anniversary!"

    anniversary_text = (
        f"{years} year" if years == 1 else f"{years} years"
    )

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}

            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">⭐</span> Work Anniversary Milestone
                </h2>

                <p style="font-size: 16px; margin: 20px 0;">
                    Dear Team,
                </p>

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
                    <p style="font-size: 24px; margin: 0;">
                        🎉 🌟 👏
                    </p>
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
    """
    Send an announcement email to all recipients.

    Args:
        title: Announcement title.
        message: Announcement message body.
        posted_by_name: Name of the person posting the announcement.
        recipient_emails: List of recipient emails.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    if not recipient_emails:
        logger.error("Cannot send announcement: recipient list is empty")
        return False

    subject = f"Announcement: {title}"

    # Format the message to preserve line breaks
    formatted_message = message.replace('\n', '<br>')

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}

            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">📢</span> {title}
                </h2>

                <p style="font-size: 16px; margin: 20px 0;">
                    Dear Team,
                </p>

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
    """
    Send a warm happy birthday email directly to the birthday person
    from the entire GooCampus team.

    Args:
        birthday_person_name: Name of the birthday person.
        birthday_person_email: Email of the birthday person.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    if not birthday_person_email:
        logger.error("Cannot send happy birthday email: no email address")
        return False

    subject = f"Happy Birthday, {birthday_person_name}! 🎂"

    first_name = birthday_person_name.split()[0] if birthday_person_name else birthday_person_name

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}

            <div style="padding: 30px; background-color: white; margin: 0;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <p style="font-size: 48px; margin: 0;">🎂🎉🎈</p>
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
                        we wish you a very happy birthday! 🥳
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
                    <p style="font-size: 36px; margin: 0;">
                        🎊 🎁 🌟 🎈 🎂
                    </p>
                </div>

                <p style="font-size: 14px; margin: 20px 0; color: #666; text-align: center;">
                    With warm wishes from all of us,<br>
                    <strong style="color: {BRAND_NAVY};">The GooCampus Team</strong> 🧡
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


if __name__ == "__main__":
    # Example usage (for testing)
    logger.info("Email utilities module loaded successfully")
