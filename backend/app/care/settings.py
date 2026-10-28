import os
from dataclasses import dataclass

def bounded(name,default,minimum,maximum):
    try:
        number=int(os.getenv(name,str(default)))
        if not minimum<=number<=maximum:
            raise ValueError()
        return number
    except ValueError:
        raise RuntimeError('invalid_care_configuration') from None

@dataclass(frozen=True)
class Settings:
    environment:str
    engine:str
    provider:str
    simulator:bool
    lease_seconds:int
    max_attempts:int
    retry_seconds:int
    policy_lifetime:int
    poll_seconds:int

def settings():
    env=os.getenv('APP_ENV','production')
    engine=os.getenv('ROBOT_CARE_ANALYSIS_ENGINE','rules')
    provider=os.getenv('ROBOT_CARE_ASSESSMENT_PROVIDER','disabled')
    simulator_value=os.getenv('ROBOT_CARE_SIMULATOR_ENABLED','false').lower()
    if simulator_value not in ('true','false'):
        raise RuntimeError('invalid_care_configuration')
    simulator=simulator_value=='true'
    if env not in ('development','test','production') or engine not in ('rules','ollama') or provider not in ('disabled','fixture','live'):
        raise RuntimeError('invalid_care_configuration')
    if env=='production' and (provider=='fixture' or simulator):
        raise RuntimeError('demo_feature_forbidden_in_production')
    if provider=='fixture' and (not os.getenv('ROBOT_CARE_FIXTURE_FILE') or os.getenv('ROBOT_CARE_DEMO_DATABASE')!='true'):
        raise RuntimeError('fixture_requires_dedicated_demo_database')
    if engine=='ollama' and (not os.getenv('ROBOT_CARE_MODEL_BASE_URL') or not os.getenv('ROBOT_CARE_MODEL_NAME')):
        raise RuntimeError('model_configuration_required')
    return Settings(env,engine,provider,simulator,bounded('ROBOT_CARE_LEASE_SECONDS',30,1,600),
                    bounded('ROBOT_CARE_MAX_ATTEMPTS',3,1,10),bounded('ROBOT_CARE_RETRY_SECONDS',2,0,300),
                    bounded('ROBOT_CARE_POLICY_SECONDS',3600,1,86400),bounded('ROBOT_CARE_POLL_SECONDS',1,1,30))

def engine_configuration():
    from care_core import CoreSettings, configuration
    active=settings()
    core=CoreSettings.from_env()
    return active,core,configuration(active.engine,core)
