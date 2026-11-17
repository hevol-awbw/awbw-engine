def pytest_configure(config):
    config.addinivalue_line("markers", "replays: engine checked against the real AWBW games in replay_archive/ (slow)")
    config.addinivalue_line("markers", "rust: the Rust engine checked against the Python engine (~2 min, needs awbw_rs)")
