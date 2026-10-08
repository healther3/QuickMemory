import socket

import pytest

from run import available_port, instance_lock


def test_dev_port_selection_excludes_backend_and_occupied_ports():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        selected = available_port(port, exclude=(port + 1,))
        assert selected not in {port, port + 1}


def test_second_instance_cannot_grade_same_database(tmp_path, monkeypatch):
    monkeypatch.setenv("QUICKMEMORY_DB", str(tmp_path / "same.db"))
    with instance_lock():
        with pytest.raises(RuntimeError, match="已经运行"):
            with instance_lock():
                pytest.fail("第二个实例不能获取锁")
    with instance_lock():
        pass
