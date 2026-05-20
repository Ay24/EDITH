"""
edith_app.core.semantic_classifier
====================================
Lightweight semantic task classifier and domain reasoner.

Provides zero-dependency domain classification for tasks and commands
so EDITH can filter, group, and reason about topics without needing
an LLM call for every simple categorization request.
"""
from __future__ import annotations

import re
from typing import NamedTuple


# ── Domain taxonomy ────────────────────────────────────────────────────────────

DOMAINS: dict[str, set[str]] = {
    "networking": {
        # Layer model
        "osi", "tcp", "udp", "ip", "tcp/ip", "tcp/udp",
        # Routing
        "ospf", "eigrp", "bgp", "rip", "isis", "routing protocol",
        "routing protocols", "eigrd",
        # Switching
        "vtp", "stp", "cdp", "switching protocol", "switching protocols",
        "etherchannel", "etherchannels", "lacp", "pagp",
        # Segmentation
        "vlan", "vlans", "trunking", "dot1q",
        # Security
        "port security", "acl", "nat", "pat", "dhcp snooping",
        # General networking
        "subnet", "subnetting", "ipv4", "ipv6", "cidr", "arp",
        "dhcp", "dns", "http", "https", "ftp", "smtp", "icmp",
        "firewall", "switch", "router", "hub", "nic", "mac address",
        "network", "networking", "lan", "wan", "man", "wlan",
    },
    "monitoring_devops": {
        "prometheus", "grafana", "zabbix", "nagios", "datadog",
        "influxdb", "elastic", "kibana", "logstash", "beats",
        "loki", "alertmanager", "telegraf",
        "ci/cd", "jenkins", "gitlab", "github actions", "circleci",
        "docker", "kubernetes", "k8s", "helm", "terraform", "ansible",
        "puppet", "chef", "salt", "devops", "sre", "observability",
        "monitoring", "metrics", "dashboards", "alerting",
    },
    "cybersecurity": {
        "burp suite", "metasploit", "nmap", "wireshark", "kali",
        "pentest", "penetration testing", "vulnerability", "exploit",
        "siem", "soc", "threat hunting", "osint", "ctf",
        "malware", "ransomware", "phishing", "social engineering",
        "zero day", "cve", "cwe", "owasp", "xss", "sqli",
        "csrf", "buffer overflow", "privilege escalation",
        "reverse shell", "forensics", "incident response",
        "red team", "blue team", "purple team",
    },
    "programming": {
        "python", "javascript", "typescript", "kotlin", "java",
        "c++", "c#", "golang", "go", "rust", "swift", "dart",
        "react", "angular", "vue", "next.js", "fastapi", "flask",
        "django", "spring", "node", "node.js", "express",
        "api", "rest", "graphql", "grpc", "microservices",
        "sql", "nosql", "mongodb", "postgresql", "redis",
        "algorithm", "data structure", "oop", "functional",
        "coding", "programming", "software", "development",
    },
    "ai_ml": {
        "llm", "llms", "rag", "embeddings", "transformers",
        "gpt", "bert", "llama", "mistral", "gemma", "claude",
        "fine-tuning", "fine tuning", "rlhf", "prompt engineering",
        "vector database", "faiss", "chroma", "pinecone", "qdrant",
        "machine learning", "deep learning", "neural network",
        "cnn", "rnn", "lstm", "attention", "diffusion",
        "stable diffusion", "gan", "reinforcement learning",
        "nlp", "computer vision", "ai", "artificial intelligence",
        "ml", "data science", "feature engineering",
    },
    "cloud": {
        "aws", "azure", "gcp", "google cloud", "cloud",
        "ec2", "s3", "lambda", "rds", "vpc",
        "load balancer", "auto scaling", "serverless",
        "cloud native", "saas", "paas", "iaas",
    },
}

# ── Domain labels (human-readable) ────────────────────────────────────────────

DOMAIN_LABELS: dict[str, str] = {
    "networking": "Networking",
    "monitoring_devops": "Monitoring / DevOps",
    "cybersecurity": "Cybersecurity",
    "programming": "Programming",
    "ai_ml": "AI / ML",
    "cloud": "Cloud",
}


class ClassifiedTask(NamedTuple):
    title: str
    domain: str          # e.g. "networking"
    domain_label: str    # e.g. "Networking"
    confidence: float    # 0.0 – 1.0


class SemanticClassifier:
    """
    Classifies task titles (or any short text) into semantic domains.

    Usage:
        clf = SemanticClassifier()
        result = clf.classify("OSPF routing configuration")
        # ClassifiedTask(title="OSPF routing configuration", domain="networking", ...)
    """

    def classify(self, text: str) -> ClassifiedTask:
        lowered = self._normalize(text)
        scores: dict[str, float] = {domain: 0.0 for domain in DOMAINS}

        tokens = set(re.split(r"[\s/\-]+", lowered))

        for domain, keywords in DOMAINS.items():
            for kw in keywords:
                if kw in lowered:
                    # Longer matches score higher
                    scores[domain] += len(kw.split()) * 1.0

        best_domain = max(scores, key=lambda d: scores[d])
        best_score = scores[best_domain]

        if best_score == 0.0:
            return ClassifiedTask(
                title=text,
                domain="general",
                domain_label="General",
                confidence=0.0,
            )

        total = sum(scores.values())
        confidence = best_score / total if total > 0 else 0.0

        return ClassifiedTask(
            title=text,
            domain=best_domain,
            domain_label=DOMAIN_LABELS.get(best_domain, best_domain.title()),
            confidence=round(confidence, 3),
        )

    def classify_many(self, texts: list[str]) -> list[ClassifiedTask]:
        return [self.classify(t) for t in texts]

    def filter_by_domain(self, texts: list[str], domain: str) -> list[str]:
        """Return only texts that classify to the given domain."""
        return [t for t in texts if self.classify(t).domain == domain]

    def exclude_domain(self, texts: list[str], domain: str) -> list[str]:
        """Return texts that do NOT classify to the given domain."""
        return [t for t in texts if self.classify(t).domain != domain]

    def group_by_domain(self, texts: list[str]) -> dict[str, list[str]]:
        """Group texts by their detected domain."""
        groups: dict[str, list[str]] = {}
        for text in texts:
            result = self.classify(text)
            groups.setdefault(result.domain_label, []).append(text)
        return groups

    # ── Intent detection helpers ───────────────────────────────────────────────

    def detect_task_filter_intent(self, command: str) -> dict | None:
        """
        Parse a natural language command into a task-filter spec.

        Returns a dict like:
            {"mode": "include" | "exclude", "domain": "networking", "label": "Networking"}
        or None if no task-filter intent is detected.
        """
        lowered = self._normalize(command)

        # Check for task-related language first
        task_signals = (
            "task", "tasks", "pending", "remaining", "queue",
            "list", "from", "ones", "those", "the ones",
        )
        has_task_signal = any(sig in lowered for sig in task_signals)
        if not has_task_signal:
            return None

        # Detect domain name in the command
        detected_domain: str | None = None
        detected_label: str | None = None
        for domain, keywords in DOMAINS.items():
            # Check if any 2+ char keyword appears in the command
            for kw in keywords:
                if len(kw) >= 4 and kw in lowered:
                    detected_domain = domain
                    detected_label = DOMAIN_LABELS.get(domain, domain.title())
                    break
            # Also check domain label itself
            label = DOMAIN_LABELS.get(domain, "").lower()
            if label and label in lowered:
                detected_domain = domain
                detected_label = DOMAIN_LABELS.get(domain, domain.title())
                break
            if detected_domain:
                break

        if not detected_domain:
            return None

        # Determine inclusion vs exclusion intent
        exclude_signals = (
            "not related", "not networking", "non-networking", "non networking",
            "unrelated", "except", "without", "excluding", "remove",
            "not about", "outside", "other than", "apart from",
            "not from", "only non", "only the ones not",
        )
        mode = "exclude" if any(sig in lowered for sig in exclude_signals) else "include"

        return {
            "mode": mode,
            "domain": detected_domain,
            "label": detected_label,
        }

    @staticmethod
    def _normalize(text: str) -> str:
        return text.lower().strip()


# Module-level singleton
_classifier = SemanticClassifier()


def classify(text: str) -> ClassifiedTask:
    return _classifier.classify(text)


def detect_task_filter_intent(command: str) -> dict | None:
    return _classifier.detect_task_filter_intent(command)


def group_tasks(titles: list[str]) -> dict[str, list[str]]:
    return _classifier.group_by_domain(titles)
