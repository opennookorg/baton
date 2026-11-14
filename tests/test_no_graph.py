from eval.no_graph import Lookup, NaiveBayes, accuracy, reorg, stream


def test_baselines_rank_the_team_seen_with_the_entities():
    train = [(["c:scheduler", "w:pod"], ["sig/scheduling"]), (["c:kubelet", "w:pod"], ["sig/node"]), (["c:scheduler"], ["sig/scheduling"])]
    test = [(["c:scheduler", "w:pod"], ["sig/scheduling"]), (["c:kubelet"], ["sig/node"]), (["w:unknown"], ["sig/apps"])]
    for model in (Lookup(), NaiveBayes()):
        for entities, teams in train:
            model.learn(entities, teams)
        assert model.rank(["w:unknown"]) == []
        assert accuracy(model, test) == {"top1": round(2 / 3, 4), "top3": round(2 / 3, 4)}


def test_stream_scores_each_issue_before_learning_it():
    rows = [(["c:scheduler"], ["sig/scheduling"])] * 2
    assert stream(NaiveBayes(), rows, lambda k: (rows, None))["stream_top1"] == 0.5


def test_reorg_relabels_only_from_the_reorg_on():
    rows = [(["c:scheduler"], ["sig/scheduling"])] * 2
    assert [teams for _, teams in reorg(rows, 1, "sig/scheduling", "sig/apps")] == [["sig/scheduling"], ["sig/apps"]]
