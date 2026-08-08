import json
from pathlib import Path


def main():
    root = Path(__file__).parents[1]
    path = root / "docs" / "context-graph.json"
    graph = json.loads(path.read_text())
    failures = []
    for requirement in graph["requirements"]:
        if requirement.get("priority") == "P0":
            if not requirement.get("tests"):
                failures.append(f"{requirement['id']}: missing test")
            if not requirement.get("demo_step"):
                failures.append(f"{requirement['id']}: missing demo step")
            for test in requirement.get("tests", []):
                test_path, separator, test_name = test.partition("::")
                if not separator or not (root / test_path).exists():
                    failures.append(f"{requirement['id']}: missing test path {test}")
                elif f"def {test_name}(" not in (root / test_path).read_text():
                    failures.append(f"{requirement['id']}: missing test function {test}")

    failures.extend(check_observability(root))

    if failures:
        raise SystemExit("Context graph gate failed:\n" + "\n".join(failures))
    print(
        f"Context graph gate passed: {len(graph['requirements'])} requirements; "
        f"{len(graph['gaps'])} explicit gaps."
    )


def check_observability(root):
    """Agent-facing health/observability must exist or it silently decays."""
    failures = []
    urls = (root / "pretalx_speakerops" / "urls.py").read_text()
    views = (root / "pretalx_speakerops" / "views.py").read_text()
    admin = (root / "pretalx_speakerops" / "admin.py").read_text()
    if "StatusView" not in views:
        failures.append("observability: StatusView missing from views.py")
    if "speakerops_status" not in urls:
        failures.append("observability: speakerops_status url missing from urls.py")
    models = (root / "pretalx_speakerops" / "models.py").read_text()
    for model in ("OnboardingTask", "SyncRun", "OutboxEvent"):
        if f"class {model}" in models and f"@admin.register({model})" not in admin:
            failures.append(f"observability: {model} not registered in admin.py")
    return failures


if __name__ == "__main__":
    main()
