from pathlib import Path

AUTH_TEMPLATE = Path("orga/templates/orga/auth/base.html")
BASE_SCRIPT = """        <script defer src="{% static 'common/js/base.js' %}"></script>"""
FORM_MEDIA = """        {% form_media %}"""


def patch_auth_script_order(template_path):
    """Load pretalx's base helpers before deferred form scripts use onReady."""
    template_path = Path(template_path)
    source = template_path.read_text()
    base_position = source.find(BASE_SCRIPT)
    media_position = source.find(FORM_MEDIA)
    if base_position < 0 or media_position < 0:
        raise RuntimeError(
            "The pinned pretalx auth template no longer matches the compatibility patch."
        )
    if base_position < media_position:
        return False
    source = source.replace(f"{BASE_SCRIPT}\n", "", 1)
    source = source.replace(FORM_MEDIA, f"{BASE_SCRIPT}\n{FORM_MEDIA}", 1)
    template_path.write_text(source)
    return True


def main():
    import pretalx

    patch_auth_script_order(Path(pretalx.__file__).parent / AUTH_TEMPLATE)


if __name__ == "__main__":
    main()
