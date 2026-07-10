"""Control plane: the privileged-action domain (fails CLOSED).

- approvals.py — classify risky actions (fail-closed), gate them behind
  single-use expiring capability tokens, and append an audit record that never
  contains prompt text or secrets.
- deploy.py — detect the environment and recommend a deploy path for the
  env-adaptive playbook (detection only; the agent executes the playbook).
"""
