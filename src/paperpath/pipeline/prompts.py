"""Prompt text for the frontier model. Judgment questions live in the Jev catalog."""

EXTRACT_SYSTEM = """\
You extract the concepts a reader must know to understand a research paper.
Return JSON: {"topics": [{"name", "aliases", "usage_description", "locations", "related_references"}]}.
Include implicit background the paper assumes, not only terms it defines.
Aim for 15 to 50 topics. Names are short concepts, not sentences.
usage_description says how THIS paper uses the topic, in one sentence.
locations are section titles or equation numbers.
related_references are titles or arXiv ids from the paper's bibliography, or an empty list.
Do not invent citations. Do not copy paragraphs from the paper.
"""

EDGES_SYSTEM = """\
You propose prerequisite pairs for topics extracted from one paper.
Return JSON: {"edges": [{"prerequisite", "dependent"}]}.
Use topic names exactly as given. prerequisite must be understood before dependent.
Propose only pairs you consider real prerequisites. Do not connect unrelated topics.
Do not add topics that are not in the list.
"""

EXPLAIN_SYSTEM = """\
You write a short note on why a topic matters for one specific paper.
Return JSON: {"explanations": [{"topic_name", "why_it_matters"}]}.
why_it_matters is two to four original sentences. Do not quote the paper or Wikipedia.
Say what the reader is missing if they skip the topic.
"""
