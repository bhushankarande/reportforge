from reportforge.cli import main


def test_main_prints_ready_message(capsys):
    main()

    captured = capsys.readouterr()
    assert captured.out == "reportforge is ready.\n"
