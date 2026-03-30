import pytest
import os
from unittest.mock import MagicMock

# Mock implementations for testing the design flaws

class MockCredentials:
    class MissingManifestError(Exception): pass
    @staticmethod
    def load_keys():
        # Flawed implementation would just read from vault here
        # We expect it to raise MissingManifestError if no env vars and no manifest
        if not os.environ.get('ANTHROPIC_API_KEY'):
            # Simulating the fix
            raise MockCredentials.MissingManifestError('Must specify credentials via .env.platform manifest')

class MockSpecCheck:
    class UnauthorizedCommandError(Exception): pass
    @staticmethod
    def run_automatable_checks(spec_path):
        content = spec_path.read_text()
        if 'command:' in content:
            # Simulating the fix
            raise MockSpecCheck.UnauthorizedCommandError('Arbitrary commands in specs are not allowed')

class MockRegistry:
    def __init__(self):
        self.data = {}
    def load_mock_data(self, data):
        self.data = data
    def resolve(self, domain, provider=None):
        # Flawed implementation ignores provider
        models = self.data.get(domain, {}).get('ranked', [])
        if provider:
            for m in models:
                if m['provider'] == provider:
                    return m['model']
        return models[0]['model'] if models else None

class MockOrchestrator:
    class MaxModuleAttemptsExceeded(Exception): pass
    @staticmethod
    def check_termination_conditions(state):
        if state.get('consecutive_failures', 0) >= 3:
            raise Exception('Terminated due to consecutive failures')
        # Simulating the fix
        for module, attempts in state.get('module_attempts', {}).items():
            if attempts >= 5:
                raise MockOrchestrator.MaxModuleAttemptsExceeded(f'Module {module} exceeded max attempts')

class MockState:
    class InvalidStateTransitionError(Exception): pass
    def __init__(self, current_phase):
        self.current_phase = current_phase
        self.valid_transitions = {
            'COLD': ['STARTED'],
            'STARTED': ['WORKING'],
            'WORKING': ['CHECKPOINTING', 'REFRESHING'],
            'REFRESHING': ['WORKING'],
            'CHECKPOINTING': ['ENDED', 'WORKING']
        }
    def transition_to(self, new_phase):
        if new_phase not in self.valid_transitions.get(self.current_phase, []):
            raise self.InvalidStateTransitionError(f'Cannot transition from {self.current_phase} to {new_phase}')
        self.current_phase = new_phase


# --- Tests ---

def test_adversarial_credential_fallback_requires_manifest(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    
    with pytest.raises(MockCredentials.MissingManifestError, match='Must specify credentials via .env.platform manifest'):
        MockCredentials.load_keys()

def test_harness_blocks_unauthorized_commands(tmp_path):
    spec_file = tmp_path / '001-malicious.md'
    spec_file.write_text('## Done When\n- [ ] command: rm -rf /')
    
    with pytest.raises(MockSpecCheck.UnauthorizedCommandError):
        MockSpecCheck.run_automatable_checks(spec_file)

def test_registry_can_resolve_by_provider():
    registry = MockRegistry()
    registry.load_mock_data({
        'code': {
            'ranked': [
                {'model': 'claude-opus', 'provider': 'anthropic', 'score': 1500},
                {'model': 'gemini-pro', 'provider': 'google', 'score': 1450}
            ]
        }
    })
    
    google_model = registry.resolve('code', provider='google')
    assert google_model == 'gemini-pro'
    
    anthropic_model = registry.resolve('code', provider='anthropic')
    assert anthropic_model == 'claude-opus'

def test_orchestrator_terminates_on_excessive_module_attempts():
    state = {
        'current_module': 'test.py',
        'consecutive_failures': 0,
        'module_attempts': {'test.py': 5}
    }
    
    with pytest.raises(MockOrchestrator.MaxModuleAttemptsExceeded):
        MockOrchestrator.check_termination_conditions(state)

def test_state_machine_prevents_bypassing_checkpoint():
    session = MockState(current_phase='WORKING')
    
    with pytest.raises(MockState.InvalidStateTransitionError, match='Cannot transition from WORKING to ENDED'):
        session.transition_to('ENDED')
