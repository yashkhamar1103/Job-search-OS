"""G2, the scope gate."""

from __future__ import annotations

from app.gates import analyse, check_block
from app.gates.g2_scope import scope_notes
from tests.conftest import assert_rejects, bullet, codes, skills, summary


def test_build_verb_with_a_used_technology_is_rejected(ctx):
    """kafka is confirmed at depth used. Wrote is a build verb."""
    result = assert_rejects(bullet("Wrote Kafka producers for order events.", facts=("acme-f2",)), ctx, "SCOPE_DEPTH")
    assert "SCOPE_DEPTH" in codes(result)


def test_non_build_verb_with_a_used_technology_passes(ctx):
    result = check_block(
        bullet("Configured Kafka producers for order events.", facts=("acme-f2",)), ctx
    )
    assert "SCOPE_DEPTH" not in codes(result)


def test_build_verb_with_a_built_technology_passes(ctx):
    result = check_block(bullet("Wrote Python services for the ingestion path."), ctx)
    assert "SCOPE_DEPTH" not in codes(result)


def test_technology_under_the_wrong_role_is_rejected(ctx):
    """postgresql is confirmed under bolt only. This bullet is under acme."""
    result = assert_rejects(
        bullet("Operated PostgreSQL for the reporting path.", role="acme"), ctx, "SCOPE_CONTEXT"
    )
    assert "SCOPE_CONTEXT" in codes(result)


def test_technology_under_the_right_role_passes(ctx):
    result = check_block(
        bullet("Operated PostgreSQL for the reporting path.", role="bolt", facts=("bolt-f1",)),
        ctx,
    )
    assert "SCOPE_CONTEXT" not in codes(result)


def test_service_listed_on_a_confirmed_platform_passes(ctx):
    """Lambda is in the aws entry's services list, so it is confirmed through
    its platform even though it has no ledger entry of its own."""
    assert ctx.bundle.ledger.get("aws_lambda") is None
    resolution = ctx.resolve("aws_lambda")
    assert resolution.confirmed
    assert resolution.via == "parent_service"

    result = check_block(bullet("Wrote AWS Lambda handlers for ingestion."), ctx)
    assert "SCOPE_SERVICE" not in codes(result)
    assert "TECH_UNCONFIRMED" not in codes(result)


def test_service_not_listed_on_its_platform_is_rejected(ctx):
    """Redshift is an AWS service the ledger never listed.

    Two findings on purpose: G1 says it is not confirmed, G2 says precisely why.
    Each gate stays independently correct rather than relying on the other.
    """
    result = assert_rejects(bullet("Wrote Amazon Redshift models for reporting."), ctx, "SCOPE_SERVICE", "TECH_UNCONFIRMED")
    assert "SCOPE_SERVICE" in codes(result)
    assert "TECH_UNCONFIRMED" in codes(result)


def test_confirmed_platform_with_no_services_list_confirms_no_sub_service(ctx):
    """Fails closed. A platform that enumerates nothing permits nothing."""
    entry = ctx.bundle.ledger.get("kafka")
    assert entry is not None and not entry.services
    assert not ctx.resolve("kafka_streams").confirmed


def test_exposure_may_not_appear_in_a_bullet(ctx):
    """docker is confirmed at depth exposure."""
    result = assert_rejects(bullet("Deployed Docker images to the cluster."), ctx, "SCOPE_EXPOSURE_IN_BULLET")
    assert "SCOPE_EXPOSURE_IN_BULLET" in codes(result)


def test_exposure_may_not_appear_in_the_skills_section(ctx):
    result = assert_rejects(skills("Platform: Docker, Python"), ctx, "SKILLS_EXPOSURE")
    assert "SKILLS_EXPOSURE" in codes(result)


def test_exposure_is_not_rejected_in_the_summary(ctx):
    """Exposure is barred from bullets and from skills. The summary is neither,
    and G1 still bounds what may appear there at all."""
    result = check_block(summary("Backend engineer who has worked alongside Docker."), ctx)
    assert "SCOPE_EXPOSURE_IN_BULLET" not in codes(result)
    assert "SKILLS_EXPOSURE" not in codes(result)


def test_technologies_from_different_roles_cannot_share_a_sentence(ctx):
    """The check per-technology context cannot make.

    kafka is confirmed under acme, postgresql under bolt. Each is true. Put them
    in one sentence and the sentence describes work that never happened.
    """
    result = assert_rejects(
        bullet("Connected Kafka topics into PostgreSQL for reporting.", role="acme"), ctx, "SCOPE_COHABITATION"
    )
    assert "SCOPE_COHABITATION" in codes(result)


def test_a_single_technology_cannot_cohabit_with_anything(ctx):
    """One participant is not cohabitation, it is SCOPE_CONTEXT named twice.

    This guard exposed the test above: it used to say "Kafka streams", which
    longest-first matching reads as the product Kafka Streams, so the sentence
    held one confirmed technology and an unconfirmed one. It passed on a group
    of one, which is not what it claimed to be testing.
    """
    result = assert_rejects(
        bullet("Operated PostgreSQL for the reporting path.", role="acme"), ctx, "SCOPE_CONTEXT"
    )
    assert "SCOPE_CONTEXT" in codes(result)
    assert "SCOPE_COHABITATION" not in codes(result)


def test_technologies_sharing_a_role_may_share_a_sentence(ctx):
    """python spans acme and bolt, kafka is acme. They share acme."""
    result = check_block(
        bullet("Configured Kafka producers from Python services.", role="acme", facts=("acme-f2",)),
        ctx,
    )
    assert "SCOPE_COHABITATION" not in codes(result)


def test_shared_role_must_be_the_bullets_own_role(ctx):
    result = assert_rejects(
        bullet("Configured Kafka producers from Python services.", role="bolt", facts=("bolt-f1",)),
        ctx,
    "SCOPE_COHABITATION",
)
    assert "SCOPE_COHABITATION" in codes(result)


def test_cohabitation_applies_to_the_summary_without_a_role(ctx):
    result = assert_rejects(summary("Engineer across Kafka and PostgreSQL platforms."), ctx, "SCOPE_COHABITATION")
    assert "SCOPE_COHABITATION" in codes(result)


def test_cohabitation_is_per_sentence_not_per_block(ctx):
    """Two sentences, one technology each, is not a blend."""
    result = check_block(
        summary("Engineer on Kafka pipelines. Separately, reporting ran on PostgreSQL."), ctx
    )
    assert "SCOPE_COHABITATION" not in codes(result)


def test_scope_note_is_surfaced_rather_than_enforced(ctx):
    """Producer side only cannot be checked in code. It is shown, not enforced."""
    block = bullet("Configured Kafka producers for order events.", facts=("acme-f2",))
    notes = scope_notes(analyse(block, ctx), ctx)
    assert ("kafka", "producer side only") in notes

    result = check_block(block, ctx)
    assert not any("scope_note" in r.detail for r in result.rejections)
