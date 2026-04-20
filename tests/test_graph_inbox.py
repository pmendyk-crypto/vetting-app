from app.graph_inbox import load_graph_inbox_config


def test_graph_inbox_config_reports_missing_required_env(monkeypatch):
    for name in (
        "GRAPH_TENANT_ID",
        "GRAPH_CLIENT_ID",
        "GRAPH_CLIENT_SECRET",
        "GRAPH_MAILBOX",
        "GRAPH_IMPORT_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    config = load_graph_inbox_config()

    assert not config.is_configured
    assert config.missing_names == [
        "GRAPH_TENANT_ID",
        "GRAPH_CLIENT_ID",
        "GRAPH_CLIENT_SECRET",
        "GRAPH_MAILBOX",
    ]
    assert config.intake_folder == "RadFlow Intake"
    assert config.import_limit == 10


def test_graph_inbox_config_reads_mailbox_settings(monkeypatch):
    monkeypatch.setenv("GRAPH_TENANT_ID", "tenant")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "client")
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GRAPH_MAILBOX", "intake@example.org")
    monkeypatch.setenv("GRAPH_INTAKE_FOLDER", "Inbox")
    monkeypatch.setenv("GRAPH_PROCESSED_FOLDER", "Processed")
    monkeypatch.setenv("GRAPH_FAILED_FOLDER", "Failed")
    monkeypatch.setenv("GRAPH_IMPORT_LIMIT", "500")

    config = load_graph_inbox_config()

    assert config.is_configured
    assert config.missing_names == []
    assert config.mailbox == "intake@example.org"
    assert config.intake_folder == "Inbox"
    assert config.processed_folder == "Processed"
    assert config.failed_folder == "Failed"
    assert config.import_limit == 50
