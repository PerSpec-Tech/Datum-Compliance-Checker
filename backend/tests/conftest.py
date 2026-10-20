def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Rewrite fixtures/expected/*.report.json from current output (review the diff!)",
    )
