"""The knowledge base's content and knowledge gaps (Super Admin stories 6.1 to 6.3).

The backend keeps Deborah's content, its versions and approvals, and the questions the Oracle
couldn't answer. The searchable knowledge base itself (chunks and embeddings) is the AI team's:
published content reaches it through the Oracle contract (`publish_knowledge`,
`withdraw_knowledge`), called in the request that publishes, archives or restores it. The
admin panel's endpoints are in app/admin/knowledge/.
"""
