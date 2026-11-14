"""Plain-code entity extraction; names carry a kind prefix (comp:, path:, word:, err:, user:) so kinds never collide."""

import re
from collections import Counter
from collections.abc import Iterable

from baton.models import Entity, EntityKind, Issue

PREFIXES: dict[EntityKind, str] = {"component": "comp:", "path": "path:", "word": "word:", "error": "err:", "reporter": "user:"}
KINDS_BY_PREFIX = {prefix: kind for kind, prefix in PREFIXES.items()}

COMPONENT_ALIASES: dict[str, tuple[str, ...]] = {
    "apiserver": ("apiserver", "kube-apiserver", "api-server", "api server", "kube apiserver"),
    "kubelet": ("kubelet",),
    "kube-proxy": ("kube-proxy", "kube proxy", "kubeproxy"),
    "scheduler": ("scheduler", "kube-scheduler", "scheduling framework"),
    "kube-controller-manager": ("kube-controller-manager", "controller-manager", "controller manager", "kcm"),
    "cloud-controller-manager": ("cloud-controller-manager", "cloud controller manager", "ccm", "cloud-provider", "cloud provider"),
    "etcd": ("etcd",),
    "kubectl": ("kubectl",),
    "kubeadm": ("kubeadm",),
    "client-go": ("client-go", "clientgo", "informer", "reflector", "workqueue"),
    "apimachinery": ("apimachinery",),
    "kube-aggregator": ("kube-aggregator", "aggregator", "apiservice", "aggregated api"),
    "apiextensions": ("apiextensions", "apiextensions-apiserver", "crd", "customresourcedefinition", "custom resource"),
    "admission": ("admission", "admission controller", "admission webhook", "mutatingwebhookconfiguration", "validatingwebhookconfiguration", "webhook"),
    "validating-admission-policy": ("validatingadmissionpolicy", "validating admission policy", "vap"),
    "cel": ("cel",),
    "rbac": ("rbac", "clusterrole", "rolebinding", "clusterrolebinding"),
    "authentication": ("authentication", "authn", "oidc", "serviceaccount token", "token request", "tokenrequest"),
    "authorization": ("authorization", "authz", "authorizer", "node authorizer"),
    "audit": ("audit", "audit log", "audit policy"),
    "serviceaccount": ("serviceaccount", "service account"),
    "secret": ("secret",),
    "configmap": ("configmap", "config map"),
    "certificate": ("certificate", "csr", "certificatesigningrequest", "tls", "x509"),
    "encryption": ("encryption", "kms", "encryptionconfiguration"),
    "cni": ("cni",),
    "csi": ("csi", "csi driver", "csidriver", "csinode"),
    "cri": ("cri", "container runtime"),
    "containerd": ("containerd",),
    "cri-o": ("cri-o", "crio"),
    "docker": ("docker", "dockershim"),
    "runc": ("runc",),
    "cadvisor": ("cadvisor",),
    "cgroup": ("cgroup", "cgroups", "cgroupv2", "cgroup v2", "cgroupv1"),
    "systemd": ("systemd",),
    "coredns": ("coredns", "kube-dns", "kubedns", "dns"),
    "iptables": ("iptables", "nftables", "ipvs", "conntrack"),
    "ingress": ("ingress", "ingressclass", "ingress controller"),
    "service": ("service", "clusterip", "nodeport", "loadbalancer", "externalname", "headless service"),
    "endpoints": ("endpoints", "endpointslice", "endpoint slice"),
    "network-policy": ("networkpolicy", "network policy"),
    "ipv6": ("ipv6", "dual-stack", "dualstack", "dual stack"),
    "gateway-api": ("gateway api", "gateway-api", "httproute"),
    "hpa": ("hpa", "horizontalpodautoscaler", "horizontal pod autoscaler", "autoscaler", "autoscaling"),
    "vpa": ("vpa", "verticalpodautoscaler", "vertical pod autoscaler"),
    "cluster-autoscaler": ("cluster-autoscaler", "cluster autoscaler"),
    "metrics-server": ("metrics-server", "metrics server", "metrics api"),
    "metrics": ("metrics", "prometheus", "metric"),
    "logging": ("logging", "klog", "structured logging", "contextual logging"),
    "tracing": ("tracing", "opentelemetry", "otel"),
    "pv": ("pv", "persistentvolume", "persistent volume"),
    "pvc": ("pvc", "persistentvolumeclaim", "persistent volume claim"),
    "storageclass": ("storageclass", "storage class"),
    "volume": ("volume", "volumemount", "volume mount", "emptydir", "hostpath", "projected volume", "subpath"),
    "volume-snapshot": ("volumesnapshot", "volume snapshot", "snapshot"),
    "attach-detach": ("attach-detach", "attachdetach", "volumeattachment", "volume attachment"),
    "nfs": ("nfs", "iscsi", "fibre channel", "rbd", "cephfs"),
    "deployment": ("deployment",),
    "replicaset": ("replicaset", "replica set", "replicationcontroller"),
    "daemonset": ("daemonset", "daemon set"),
    "statefulset": ("statefulset", "stateful set"),
    "job": ("job", "cronjob", "cron job", "indexed job"),
    "pdb": ("pdb", "poddisruptionbudget", "pod disruption budget", "disruption"),
    "garbage-collector": ("garbage collector", "garbage collection", "ownerreference", "ownerreferences", "finalizer"),
    "namespace": ("namespace",),
    "pod": ("pod",),
    "node": ("node",),
    "container": ("container",),
    "init-container": ("init container", "initcontainer", "sidecar", "sidecar container"),
    "probe": ("probe", "liveness", "readiness", "startup probe", "livenessprobe", "readinessprobe"),
    "eviction": ("eviction", "evict", "evicted", "preemption", "preempt"),
    "taint": ("taint", "toleration", "taints"),
    "affinity": ("affinity", "anti-affinity", "nodeaffinity", "podaffinity", "topology spread", "topologyspreadconstraints"),
    "resource-quota": ("resourcequota", "resource quota", "limitrange", "limit range"),
    "resources": ("cpu", "memory", "hugepages", "oom", "oomkilled", "cpu manager", "cpumanager", "memory manager", "topology manager"),
    "device-plugin": ("device plugin", "device-plugin", "deviceplugin", "gpu"),
    "dra": ("dra", "dynamic resource allocation", "resourceclaim", "resourceslice", "deviceclass"),
    "in-place-resize": ("in-place resize", "inplace resize", "in-place pod resize", "pod resize"),
    "image": ("image pull", "imagepullbackoff", "errimagepull", "image", "registry"),
    "seccomp": ("seccomp", "apparmor", "selinux", "securitycontext", "security context"),
    "pod-security": ("pod security", "podsecurity", "psp", "podsecuritypolicy", "pod security admission"),
    "user-namespaces": ("user namespaces", "userns", "user namespace"),
    "windows": ("windows",),
    "kubemark": ("kubemark",),
    "e2e": ("e2e", "conformance", "ginkgo", "e2e test"),
    "kind": ("kind cluster",),
    "kustomize": ("kustomize",),
    "openapi": ("openapi", "swagger", "openapi v3"),
    "apply": ("server-side apply", "server side apply", "ssa", "managedfields", "managed fields", "kubectl apply"),
    "watch": ("watch", "watchlist", "watch cache", "watchcache", "cacher"),
    "feature-gate": ("feature gate", "feature-gate", "featuregate", "feature gates"),
    "leader-election": ("leader election", "leaderelection", "lease"),
    "golang": ("golang",),
    "dependency": ("dependency", "dependencies", "go.mod", "vendor"),
    "event": ("event", "events"),
    "kms": ("kms plugin",),
    "node-lifecycle": ("node lifecycle", "nodelifecycle", "node controller", "notready", "not ready"),
    "graceful-shutdown": ("graceful shutdown", "graceful node shutdown", "terminationgraceperiodseconds"),
    "static-pod": ("static pod", "static pods", "mirror pod"),
    "port-forward": ("port-forward", "portforward", "port forward", "exec", "attach", "kubectl exec", "kubectl logs"),
    "flowcontrol": ("apf", "priority and fairness", "flowcontrol", "flowschema", "prioritylevelconfiguration"),
    "storage-version": ("storage version", "storageversion", "storage migration"),
}

COMPONENT_BY_ALIAS = {alias: name for name, aliases in COMPONENT_ALIASES.items() for alias in aliases}
SEPARATORS = re.compile(r"[\s\-_]+")
COMPONENT_BY_SQUASHED = {SEPARATORS.sub("", alias): name for alias, name in COMPONENT_BY_ALIAS.items()}
COMPONENT_PATTERN = re.compile(
    r"(?<![a-z0-9_\-./])(" + "|".join(re.escape(a).replace(r"\ ", r"[\s\-_]?") for a in sorted(COMPONENT_BY_ALIAS, key=len, reverse=True)) + r")s?(?![a-z0-9_\-])"
)

PATH_ROOTS = ("pkg", "cmd", "staging", "test", "plugin", "cluster", "hack", "build", "k8s.io", "vendor")
PATH_PATTERN = re.compile(r"(?<![a-z0-9_\-.])((?:" + "|".join(re.escape(r) for r in PATH_ROOTS) + r")/[a-z0-9_\-./]+)")
PATH_DEPTH = 3

STOP_WORDS = frozenset(
    """
    a about above after again against all also always am an and any are aren as at be because been before being below
    between both but by can cannot could did didn do does doesn doing don down during each even ever every few for from
    further get gets getting got had has hasn have having he her here hers him his how however i if in into is isn it its
    itself just let like may me might more most much must my need needs no nor not now of off on once only or other our
    out over own same see seems seem she should shouldn since so some still such than that the their them then there these
    they this those though through thus to too under until up upon us use used uses using very via was wasn we were weren
    what when where whether which while who whom why will with within without won would yet you your
    able add added adding allow allows another around automatically back based better call called case cause causes
    change changes check could correctly current currently doesnt don't due either enough etc existing expected fail
    failed failing fails failure fix fixed fixes following happen happens incorrect incorrectly instead issue issues
    k8s keep kubernetes make makes many missing new non one ones possible properly really related remove removed request
    required return returns right set should show shows something sometimes specific support supported take two unable
    unexpected via want way well wrong yaml error errors bug
    """.split()
)

FENCED_CODE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
HTML_TAG = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
HEADING_LINE = re.compile(r"^\s*#+.*$", re.MULTILINE)
URL = re.compile(r"https?://\S+")
INLINE_CODE = re.compile(r"`([^`\n]{3,200})`")
ERROR_AFTER = re.compile(r"\berr(?:or)?\s*[:=]\s*\"?([^\n\"]{3,300})", re.IGNORECASE)
WORD = re.compile(r"[a-z][a-z0-9_\-]*[a-z0-9]")
PHRASE_TOKEN = re.compile(r"[a-z][a-z0-9]*")
ERROR_WORDS = 6
VAGUE_PHRASES = frozenset("true false nil null none name kind value values error err failed status running master main yes no".split())
WORD_SYNONYMS = {"flaky": "flake", "flaking": "flake", "flakes": "flake", "flakiness": "flake"}


def strip_noise(body: str) -> str:
    """Drop HTML comments, tags and template heading lines, keeping code blocks."""
    return HEADING_LINE.sub(" ", HTML_TAG.sub(" ", HTML_COMMENT.sub(" ", body)))


def prose(text: str) -> str:
    """Drop fenced code blocks and URLs, leaving the written prose."""
    return URL.sub(" ", FENCED_CODE.sub(" ", text))


def components(text: str) -> set[str]:
    """Canonical component names mentioned in lowercase text."""
    return {COMPONENT_BY_SQUASHED[SEPARATORS.sub("", match)] for match in COMPONENT_PATTERN.findall(text)}


def normalise_path(raw: str) -> str | None:
    """Reduce a file or Go package path to its first PATH_DEPTH directory segments."""
    segments = [s for s in raw.strip("./").split("/") if s and s not in (".", "..")]
    while segments and segments[0] == "vendor":
        segments = segments[1:]
    if segments[:2] == ["staging", "src"]:
        segments = segments[2:]
    if segments[:2] == ["k8s.io", "kubernetes"]:
        segments = segments[2:]
    directories = []
    for segment in segments:
        if "." in segment and segment != "k8s.io":
            break
        directories.append(segment)
    directories = directories[: PATH_DEPTH + (directories[:1] == ["k8s.io"] and directories[2:3] == ["pkg"])]
    if len(directories) < 2 or directories[0] not in PATH_ROOTS or directories[0] in ("staging", "vendor"):
        return None
    return "/".join(directories)


def paths(text: str) -> set[str]:
    """Normalised repository and Go package paths found in lowercase text."""
    return {p for p in (normalise_path(m) for m in PATH_PATTERN.findall(text)) if p}


def phrase(raw: str) -> str | None:
    """Normalise an error phrase to at most ERROR_WORDS lowercase word tokens."""
    if "/" in raw:
        return None
    text = " ".join(PHRASE_TOKEN.findall(raw.lower())[:ERROR_WORDS])
    return text if len(text) >= 3 and text not in VAGUE_PHRASES and text not in STOP_WORDS else None


def errors(full_text: str, prose_text: str) -> set[str]:
    """Error phrases: inline code in prose, plus text after `error:` anywhere."""
    found = [phrase(m) for m in INLINE_CODE.findall(prose_text)]
    found += [phrase(m) for m in ERROR_AFTER.findall(full_text)]
    return {p for p in found if p}


def singular(word: str) -> str:
    """Strip a simple English plural ending."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and len(word) > 3 and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def title_words(title: str) -> set[str]:
    """Lowercased title words minus stop words, numbers and words already captured as components."""
    words = set()
    title_without_paths = " ".join(token for token in title.lower().split() if "/" not in token)
    for raw in WORD.findall(title_without_paths):
        word = WORD_SYNONYMS.get(raw) or singular(raw.strip("-_"))
        if len(word) < 3 or word in STOP_WORDS or raw in STOP_WORDS:
            continue
        if SEPARATORS.sub("", raw) in COMPONENT_BY_SQUASHED or SEPARATORS.sub("", word) in COMPONENT_BY_SQUASHED:
            continue
        words.add(word)
    return words


def extract(title: str, body: str, reporter: str) -> list[Entity]:
    """Extract the distinct entities of one issue, sorted by name."""
    title_text = title.lower()
    full_text = strip_noise(body or "").lower()
    prose_text = prose(full_text)
    found_components = components(title_text) | components(prose_text)
    names = {PREFIXES["component"] + c for c in found_components}
    names |= {PREFIXES["path"] + p for p in paths(title_text) | paths(full_text)}
    names |= {PREFIXES["word"] + w for w in title_words(title)}
    names |= {PREFIXES["error"] + e for e in errors(title_text + "\n" + full_text, prose(title_text) + "\n" + prose_text)}
    if reporter:
        names.add(PREFIXES["reporter"] + reporter.lower())
    return [Entity(name, kind_of(name)) for name in sorted(names)]


def extract_issue(issue: Issue) -> list[Entity]:
    """Extract entities from an Issue."""
    return extract(issue.title, issue.body, issue.reporter)


def kind_of(name: str) -> EntityKind:
    """The kind encoded in an entity name's prefix."""
    return KINDS_BY_PREFIX[name[: name.index(":") + 1]]


def display_name(name: str) -> str:
    """The entity name without its kind prefix."""
    return name.split(":", 1)[1]


def build_vocabulary(issues: Iterable[Issue], min_issues: int = 3) -> dict[str, EntityKind]:
    """Map each entity name seen in at least `min_issues` issues to its kind, counting once per issue."""
    counts = Counter(entity.name for issue in issues for entity in set(extract_issue(issue)))
    return {name: kind_of(name) for name, count in sorted(counts.items()) if count >= min_issues}
