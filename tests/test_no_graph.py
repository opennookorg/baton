from eval.no_graph import Lookup, NaiveBayes, accuracy


def test_baselines_rank_the_team_seen_with_the_entities():
    train = [(["c:scheduler", "w:pod"], ["sig/scheduling"]), (["c:kubelet", "w:pod"], ["sig/node"]), (["c:scheduler"], ["sig/scheduling"])]
    test = [(["c:scheduler", "w:pod"], ["sig/scheduling"]), (["c:kubelet"], ["sig/node"]), (["w:unknown"], ["sig/apps"])]
    for model in (Lookup(), NaiveBayes()):
        for entities, teams in train:
            model.learn(entities, teams)
        assert model.rank(["w:unknown"]) == []
        assert accuracy(model, test) == {"top1": round(2 / 3, 4), "top3": round(2 / 3, 4)}
