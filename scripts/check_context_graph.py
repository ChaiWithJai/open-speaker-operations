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
    if failures:
        raise SystemExit("Context graph gate failed:\n" + "\n".join(failures))
    print(
        f"Context graph gate passed: {len(graph['requirements'])} requirements; "
        f"{len(graph['gaps'])} explicit gaps."
    )


if __name__ == "__main__":
    main()
