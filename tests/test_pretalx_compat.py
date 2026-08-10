from pretalx_speakerops.pretalx_compat import (
    BASE_SCRIPT,
    FORM_MEDIA,
    patch_auth_script_order,
)


def test_auth_template_patch_orders_base_helpers_before_form_media(tmp_path):
    template = tmp_path / "base.html"
    template.write_text(f'<head>\n{FORM_MEDIA}\n<meta name="viewport">\n{BASE_SCRIPT}\n</head>\n')

    assert patch_auth_script_order(template) is True
    patched = template.read_text()
    assert patched.index(BASE_SCRIPT) < patched.index(FORM_MEDIA)
    assert patch_auth_script_order(template) is False


def test_auth_template_patch_fails_closed_when_upstream_changes(tmp_path):
    template = tmp_path / "base.html"
    template.write_text("<head>{% form_media %}</head>")

    try:
        patch_auth_script_order(template)
    except RuntimeError as error:
        assert "no longer matches" in str(error)
    else:
        raise AssertionError("An unknown upstream template must fail the image build.")
