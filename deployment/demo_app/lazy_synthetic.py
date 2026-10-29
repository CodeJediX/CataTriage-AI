"""Keep the optional simulation's PyTorch runtime out of ordinary sign-in requests."""
GRADE_NAMES=["Grade 0 - clear","Grade 1 - mild","Grade 2 - moderate","Grade 3 - advanced"]


class _LazySimulation:
    def __getattr__(self,name):
        from .synthetic_models import synthetic_provider
        return getattr(synthetic_provider,name)


synthetic_provider=_LazySimulation()
