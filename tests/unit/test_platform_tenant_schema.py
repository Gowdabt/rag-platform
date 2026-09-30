from app.api.errors import format_validation_detail
from app.api.v1.platform import PlatformTenantIn
from app.application.identity import demo_seed_email
from pydantic import ValidationError


def test_platform_tenant_in_accepts_company_name_and_slugifies():
    body = PlatformTenantIn.model_validate(
        {
            "company_name": "Salesforce",
            "slug": "Salesforce",
            "admin_name": "Gowda",
            "admin_email": "hbt@salesforce.com",
        }
    )
    assert body.name == "Salesforce"
    assert body.slug == "salesforce"
    assert body.admin_password is None


def test_platform_tenant_in_optional_password_blank_is_none():
    body = PlatformTenantIn.model_validate(
        {
            "name": "Acme",
            "slug": "acme",
            "admin_name": "Ada",
            "admin_email": "ada@example.com",
            "admin_password": "   ",
        }
    )
    assert body.admin_password is None


def test_platform_tenant_in_short_password_rejected():
    try:
        PlatformTenantIn.model_validate(
            {
                "name": "Acme",
                "slug": "acme",
                "admin_name": "Ada",
                "admin_email": "ada@example.com",
                "admin_password": "short",
            }
        )
    except ValidationError as exc:
        assert "admin_password" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_format_validation_detail_names_fields():
    detail = format_validation_detail(
        [
            {"loc": ("body", "name"), "msg": "Field required", "type": "missing"},
            {"loc": ("query", "limit"), "msg": "Input should be greater than or equal to 1", "type": "greater_than_equal"},
        ]
    )
    assert "name: Field required" in detail
    assert "limit:" in detail


def test_demo_seed_email_uses_role_and_tenant_slug():
    assert demo_seed_email("Member", "salesforce") == "member@salesforce.demo"
    assert demo_seed_email("Viewer", "salesforce") == "viewer@salesforce.demo"
    assert demo_seed_email("Member", "salesforce", n=2) == "member-2@salesforce.demo"


def test_demo_seed_email_skips_claimed_admin_pattern():
    claimed = {"member@acme.demo"}
    n = 1
    email = demo_seed_email("Member", "acme", n=n)
    while email in claimed:
        n += 1
        email = demo_seed_email("Member", "acme", n=n)
    assert email == "member-2@acme.demo"
