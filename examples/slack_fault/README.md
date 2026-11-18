# Example: custom fault plugin

A minimal example of a third-party AgentChaos fault plugin.

This fault simulates a Slack API rate limit: the tool call is blocked and
returns a `429` with a `retry_after` header value embedded in the message.

## Structure

```
slack_fault/
  pyproject.toml   # registers the fault via entry-points
  slack_fault.py   # the fault class
```

## Install

```sh
pip install -e .
# now agentchaos faults shows "slack_rate_limit"
```

## Use

```yaml
# policy.yaml
schema_version: 1
seed: 42
rules:
  - tools: "post_message"
    fault: slack_rate_limit
    probability: 0.4
    params:
      retry_after: 30
```

```sh
agentchaos run --scenario ticketing --policy policy.yaml --trials 20
```
