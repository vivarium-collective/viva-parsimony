"""The pbg_parsimony import name stays working (deprecated) after the rename."""
import warnings


def test_pbg_parsimony_still_imports_and_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import pbg_parsimony  # noqa: F401
    assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_pbg_parsimony_submodule_redirects_to_viva_parsimony():
    import viva_parsimony.recipe as real
    import pbg_parsimony.recipe as shimmed
    assert shimmed is real            # meta-path finder aliases to the real module
