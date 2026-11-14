from baton.entities import COMPONENT_BY_SQUASHED, COMPONENT_BY_ALIAS, build_vocabulary, display_name, extract, kind_of, normalise_path
from baton.models import Entity, Issue


def names(title, body="", reporter=""):
    return {entity.name for entity in extract(title, body, reporter)}


def test_component_aliases_normalise():
    assert "comp:apiserver" in names("kube-apiserver crashes on startup")
    assert "comp:kube-proxy" in names("kube proxy drops traffic")
    assert "comp:statefulset" in names("StatefulSets stuck rolling")
    assert "comp:hpa" in names("Horizontal Pod Autoscaler ignores metrics")


def test_squashed_aliases_never_collide():
    for alias, name in COMPONENT_BY_ALIAS.items():
        assert COMPONENT_BY_SQUASHED[alias.replace(" ", "").replace("-", "").replace("_", "")] == name


def test_component_word_is_not_also_a_title_word():
    found = names("kubelet restarts")
    assert "comp:kubelet" in found
    assert "word:kubelet" not in found
    assert "word:restart" in found


def test_title_words_drop_stop_words_and_plurals():
    assert names("The timeouts are failing when draining") >= {"word:timeout", "word:draining"}
    assert not {"word:the", "word:are", "word:when", "word:failing"} & names("The timeouts are failing when draining")


def test_paths_normalise_to_three_segments():
    assert normalise_path("pkg/kubelet/cm/cpumanager/policy.go") == "pkg/kubelet/cm"
    assert normalise_path("staging/src/k8s.io/client-go/tools/cache/reflector.go:123") == "k8s.io/client-go/tools"
    assert normalise_path("k8s.io/kubernetes/pkg/scheduler/framework") == "pkg/scheduler/framework"
    assert normalise_path("vendor/k8s.io/api/core/v1") == "k8s.io/api/core"
    assert normalise_path("staging/src/k8s.io/apiserver/pkg/storage/cacher/cacher.go") == "k8s.io/apiserver/pkg/storage"
    assert normalise_path("pkg/kubelet.go") is None
    body = "panic at\n```\nk8s.io/kubernetes/pkg/kubelet/kuberuntime.(*m).Sync()\n\t/go/src/pkg/kubelet/kuberuntime/manager.go:42\n```"
    assert "path:pkg/kubelet/kuberuntime" in names("crash", body)


def test_error_phrases_cut_to_six_words():
    found = names("x", 'Pod fails with error: "failed to create pod sandbox: rpc error: code = Unknown desc"')
    assert "err:failed to create pod sandbox rpc" in found
    assert "err:connection refused" in names("x", "it logs `connection refused` sometimes")


def test_title_paths_and_vague_inline_code_are_not_words_or_phrases():
    found = names("Flaky test in pkg/kubelet/cm", "set it to `true` or `pkg/x/y` on `kube-proxy`")
    assert "comp:kube-proxy" in found
    assert "word:flake" in found and "word:pkg" not in found
    assert not {n for n in found if n.startswith("err:")}


def test_template_noise_is_stripped():
    body = "<!-- Please fill in -->\n#### Container runtime (CRI) and version\n#### Related plugins (CNI, CSI, ...)\nit broke"
    assert not {n for n in names("x", body) if n.startswith("comp:")}


def test_inline_code_inside_fenced_blocks_is_not_an_error_phrase():
    assert not {n for n in names("x", "```\n`oops thing`\n```") if n.startswith("err:")}


def test_reporter_and_kinds():
    entities = extract("Scheduler panic", "", "SomeUser")
    assert Entity("user:someuser", "reporter") in entities
    assert all(kind_of(entity.name) == entity.kind for entity in entities)
    assert display_name("path:pkg/kubelet/cm") == "pkg/kubelet/cm"


def test_build_vocabulary_counts_once_per_issue():
    def issue(number, title, reporter):
        return Issue(number, title, "", "2024-01-01T00:00:00Z", reporter, ("sig/node",))

    issues = [issue(1, "kubelet kubelet", "a"), issue(2, "kubelet", "a"), issue(3, "etcd", "b"), issue(4, "kubelet etcd", "c")]
    vocabulary = build_vocabulary(issues, min_issues=3)
    assert vocabulary == {"comp:kubelet": "component"}
