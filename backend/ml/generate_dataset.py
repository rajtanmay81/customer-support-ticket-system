"""
Generates a synthetic "historical tickets" dataset for training the
category + priority classifiers. In a real system this would be an
export of past tickets; here we template-generate plausible text so
the ML pipeline has something realistic to learn from.
"""
import csv
import random
from pathlib import Path

random.seed(42)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "historical_tickets.csv"

# Each category has a pool of subject/description templates and a
# realistic priority distribution (not 1:1 - e.g. billing is rarely critical).
CATEGORY_TEMPLATES = {
    "technical_issue": {
        "subjects": [
            "App crashes on startup",
            "Unable to sync data across devices",
            "Dashboard is loading extremely slowly",
            "Getting a 500 error when saving changes",
            "Integration with our CRM stopped working",
            "Push notifications are not being delivered",
            "Export to CSV is failing silently",
            "API requests are timing out",
        ],
        "descriptions": [
            "Every time I open the app it crashes within a few seconds. I've tried reinstalling but the issue persists.",
            "Data isn't syncing between my laptop and phone anymore. This started happening after the last update.",
            "The main dashboard takes over 30 seconds to load, it used to be instant. Other pages seem fine.",
            "When I try to save my project settings I get an internal server error. No changes are being persisted.",
            "Our Salesforce integration was working fine last week but now nothing syncs over. No error message shown.",
            "We rely on push notifications for alerts and none have come through in the last two days.",
            "Clicking 'Export to CSV' just spins forever and nothing downloads, no error in the console.",
            "Several API calls from our backend are timing out after 30s, this is affecting our production pipeline.",
        ],
        "priority_weights": {"low": 0.15, "medium": 0.40, "high": 0.35, "critical": 0.10},
    },
    "billing": {
        "subjects": [
            "Charged twice for the same subscription",
            "Invoice shows incorrect tax amount",
            "Need a refund for accidental upgrade",
            "Credit card declined but subscription still active",
            "Where can I download my past invoices",
            "Discount code was not applied at checkout",
            "Billing cycle date is wrong on my account",
        ],
        "descriptions": [
            "I was billed twice this month for the same plan, can you please refund the duplicate charge.",
            "My latest invoice has a tax line that doesn't match my region's rate, could you review it.",
            "I accidentally upgraded to the enterprise plan and would like a refund and downgrade back to standard.",
            "My card was declined per the email you sent, but I can still access the paid features. Please clarify billing status.",
            "I need copies of my invoices from the last 6 months for our accounting team.",
            "I used the promo code SAVE20 at checkout but the discount never applied to my total.",
            "My billing cycle used to renew on the 1st and now it shows the 15th, not sure why it changed.",
        ],
        "priority_weights": {"low": 0.45, "medium": 0.40, "high": 0.13, "critical": 0.02},
    },
    "access_issue": {
        "subjects": [
            "Locked out of my account after password reset",
            "Two-factor authentication code never arrives",
            "Cannot invite new team members",
            "SSO login redirects to an error page",
            "Forgot password link is not working",
            "Account shows as suspended without explanation",
        ],
        "descriptions": [
            "I reset my password but now I can't log in at all, it just says invalid credentials.",
            "The 2FA text message never arrives so I can't complete login, tried resending multiple times.",
            "As an admin I try to invite teammates but the invite button does nothing.",
            "Our SSO login through Okta redirects to a generic error page instead of the dashboard.",
            "I clicked 'forgot password' and never received the reset email, checked spam too.",
            "I logged in today and it says my account is suspended, I have no idea why since I pay on time.",
        ],
        "priority_weights": {"low": 0.05, "medium": 0.30, "high": 0.45, "critical": 0.20},
    },
    "product_bug": {
        "subjects": [
            "Totals on the report page don't add up",
            "Dark mode breaks the settings menu layout",
            "Duplicate entries appearing in the task list",
            "File attachments are corrupted after upload",
            "Currency symbol shows wrong for EUR accounts",
            "Search results are missing recently added items",
        ],
        "descriptions": [
            "The summary total on the monthly report doesn't match the sum of individual line items.",
            "When dark mode is enabled the settings menu overlaps with the sidebar and is unusable.",
            "Tasks I create sometimes appear twice in the list after refreshing the page.",
            "Files I upload show as corrupted when downloaded again, tested with PDFs and images.",
            "Accounts set to EUR are showing a dollar sign instead of the euro symbol everywhere.",
            "Anything I've added in the last hour doesn't show up in search results, only older items do.",
        ],
        "priority_weights": {"low": 0.20, "medium": 0.45, "high": 0.30, "critical": 0.05},
    },
    "urgent_escalation": {
        "subjects": [
            "Entire workspace is down for our whole company",
            "Production data appears to have been deleted",
            "Security concern: unauthorized login detected",
            "Service outage affecting all customers",
            "Payment processing is completely broken sitewide",
            "Possible data breach, need immediate response",
        ],
        "descriptions": [
            "Our entire company workspace is inaccessible right now, this is blocking all of our teams from working.",
            "We just noticed a large chunk of production data is missing, this looks like accidental or malicious deletion.",
            "We detected a login from an unrecognized location and device, this account may be compromised.",
            "It looks like the service is down for everyone, not just us, please escalate immediately.",
            "No customer can complete checkout right now, this is actively costing us revenue every minute.",
            "We have reason to believe customer data may have been exposed, we need to talk to someone immediately.",
        ],
        "priority_weights": {"low": 0.0, "medium": 0.02, "high": 0.13, "critical": 0.85},
    },
}

PRIORITIES = ["low", "medium", "high", "critical"]
SAMPLES_PER_CATEGORY = 220

# Urgency phrasing that actually correlates with priority, independent of category -
# this is what gives the priority classifier real textual signal to learn from,
# rather than having it implicitly memorize category -> priority weights.
URGENCY_PHRASES = {
    "low": [
        "No rush at all, whenever you get a chance is fine.",
        "This is a minor annoyance, not blocking any work.",
        "Just flagging this for whenever it's convenient to look at.",
        "Low priority from my side, just wanted it on your radar.",
    ],
    "medium": [
        "It's a bit inconvenient but I have a workaround for now.",
        "Would appreciate a fix in the next few days.",
        "Not blocking me completely, but it is slowing my work down.",
        "Please take a look when you have a chance this week.",
    ],
    "high": [
        "This is significantly impacting my ability to get work done.",
        "I need this resolved soon, it's affecting my whole team.",
        "This is a serious problem that needs attention today.",
        "Please prioritize this, it's causing real disruption.",
    ],
    "critical": [
        "This needs immediate attention, we cannot continue working.",
        "Please escalate this right now, it is critical.",
        "This is a top priority emergency, we need help ASAP.",
        "Time-sensitive and urgent, this is costing us money every minute.",
    ],
}


def weighted_choice(weights: dict) -> str:
    return random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]


def main():
    rows = []
    for category, spec in CATEGORY_TEMPLATES.items():
        for _ in range(SAMPLES_PER_CATEGORY):
            subject = random.choice(spec["subjects"])
            priority = weighted_choice(spec["priority_weights"])
            base_description = random.choice(spec["descriptions"])
            urgency_phrase = random.choice(URGENCY_PHRASES[priority])
            description = f"{base_description} {urgency_phrase}"
            rows.append(
                {
                    "subject": subject,
                    "description": description,
                    "category": category,
                    "priority": priority,
                }
            )

    random.shuffle(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["subject", "description", "category", "priority"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} synthetic historical tickets to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
