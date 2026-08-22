import json

from curriculum import Domain, Topic
from praxis.construct import ConstructionResult
from praxis.promote import domain_numbering_failures, promote_topic

from test_audit import notebook


def test_domain_numbering_matches_manifest_and_reserves_six():
    assert domain_numbering_failures() == []


def test_promotion_refuses_to_record_without_a_valid_checkset(tmp_path, monkeypatch):
    domain = Domain("01-symbolic-ai-logic", "Symbolic AI & Logic", "", ())
    topic = Topic("new-topic", "New Topic", recommended=True)
    notebooks = tmp_path / "notebooks"
    path = notebooks / domain.dir / "new-topic.ipynb"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(notebook()))
    monkeypatch.setattr("curriculum.NOTEBOOKS_DIR", notebooks)
    monkeypatch.setattr(
        "praxis.promote.construct_topic",
        lambda *args, **kwargs: ConstructionResult(
            path=path, slug=topic.slug, title=topic.title, status="skipped"
        ),
    )
    gap = tmp_path / "gap.md"
    gap.write_text("### Symbolic AI & Logic\n\n## 2. Recommended additions\n\n- **New Topic**\n")

    result = promote_topic(domain, topic, gap_path=gap)

    assert not result.ok
    assert "knowledge checks are absent" in " ".join(result.failures)
    assert "- **New Topic**" in gap.read_text()


def test_domain_number_six_is_rejected(tmp_path):
    root = tmp_path / "notebooks"
    for name in ("01-one", "06-reused"):
        (root / name).mkdir(parents=True)
    domains = [
        Domain("01-one", "One", ""),
        Domain("06-reused", "Reused", ""),
    ]
    assert any("06" in failure for failure in domain_numbering_failures(root=root, domains=domains))
