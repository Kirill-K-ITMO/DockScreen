import pytest
from src.analysis.smaa import MAX_CANDIDATES, analyze_preferences
from src.reporting.csv_import import MAX_ROWS


def test_public_input_caps_are_100k():
    assert MAX_CANDIDATES == MAX_ROWS == 100000


def test_100k_feasible_rows_rejected_by_memory_before_dense_allocation(monkeypatch):
    import src.analysis.smaa as engine
    rows = [{'id': str(i)} for i in range(100000)]
    def no_allocation(*args, **kwargs):
        raise AssertionError('Must reject before utility or dense matrices')
    monkeypatch.setattr(engine, 'utility_matrix', no_allocation)
    scales = [{'key':'x','direction':'max','worst':0,'best':1,'alpha':1}]
    with pytest.raises(ValueError, match='256 MiB'):
        analyze_preferences(rows, scales, iterations=1)
