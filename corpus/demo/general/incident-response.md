# Incident Response

## Severity levels

SEV1 means a complete outage or a safety risk to people. The on-call engineer must respond within 15 minutes. SEV2 means a major feature is broken for many customers, and the response time is 30 minutes. SEV3 means a minor issue with a workaround, and it is handled by the next business day.

## Roles

Every SEV1 and SEV2 incident has an incident commander. The incident commander coordinates the response and decides when the incident is resolved. A communications lead posts updates to the status page every 30 minutes.

## During an incident

Open a dedicated incident channel named after the date and a short description. Write down every action and its time in the channel so that the timeline can be rebuilt later.

## Postmortems

A written postmortem is due within 5 business days after a SEV1 or SEV2 incident. Postmortems are blameless: they describe what happened and how to improve the system, not who made a mistake.

## Customer communication

The customer success team contacts affected customers within 2 hours of a SEV1 declaration.
