The AWS SSM Parameter Store is simple and great for AWS config bits,
but SSM only preserves 100 versions and maintains no record of
deletion.

To enable point-in-time restore, including deleted versions and entire
recursive trees, we use an s3 bucket with versioning enabled as a
backend.

This project includes all the pieces to both backup and restore SSM
Params to a point in time.

* Backup: Eventbridge -> SQS -> Lambda -> S3
  * launch cloudformation stack from
    [template](https://github.com/newvoll/ssmbak/blob/main/ssmbak/data/cfn.yml)
    with `ssmbak-stack <name> create`.
* Restore with either:
    * `ssmbak restore` cli, which uses
	* the well-tested [library](https://ssmbak.readthedocs.io/en/latest/ssmbak.restore.html#module-ssmbak.restore.actions)
```
from ssmbak.restore.actions import ParamPath
ParamPath.restore()
```

# Quickstart
You'll need credentials that can create IAM resources with
Cloudformation (to assign minimal permissions to the lambda role).

```
pip install ssmbak
ssmbak-stack <SSMBAK_STACKNAME> create
```

That's it. All new params will automatically be backed-up and
available for `ssmbak` point-in-time restore via CLI or lib, like:

`ssmbak preview /my/ssm/path/ 2024-06-15T17:56:58`

> You need a bunch of shady permissions to create the stack. Look for such errors if it fails.

[CLI and Lib Tutorials](https://github.com/newvoll/ssmbak/blob/main/TUTORIAL.md) available, CLI codified in experimental script `tests/verify_cli_tutorial.sh` that does the steps.

# Backup Guarantees

## Event Time Preservation

- **Regular backups (Create/Update)**: Event time is preserved via S3 object tags (`ssmbakTime`), ensuring accurate point-in-time restore even during Lambda processing delays or outages.

- **Delete markers**: Event time cannot be preserved because S3 delete markers don't support tags. Delete markers use S3's `LastModified` timestamp (when the Lambda processed the delete) instead of the original event time.

## Implications During Outages

If SQS messages queue up during an outage and delete events are processed late:

- **Worst case**: A parameter that was deleted may appear with its last value instead of showing as deleted when querying for a time between the actual deletion and when the Lambda processed it.

- **Safe failure mode**: You might restore previously deleted data (resurrection), but you will never lose data that actually existed at the query time.

**Example**:
- T1: Parameter has value "important"
- T2: Parameter deleted
- T3-T10: Lambda outage (delete event queued)
- T11: Lambda processes delete, creates delete marker with LastModified=T11
- Query at T5: Returns "important" (last backup before T5) instead of showing deleted

This is an inherent limitation of S3 delete markers not supporting tags.


# Scripts
* `ssmbak-all` will back up all SSM params to the bucket. You can also give it a path.

* `ssmbak-stack` can create, update and give you info about the stack,
  including all its resources.

* `-h` for more info.

Seed backups for all previously set SSM Params with `ssmbak-all`. It
will just show you what would be backed-up. `--do-it` to actually
perform the backups.

If you download a new version, best to get that same version running in the Lambda with:

```ssmbak-stack <SSMBAK_STACKNAME> update```

The lambda is configured to write logs to cloudwatch.

```
SSMBAK_LAMBDANAME=`ssmbak-stack $SSMBAK_STACKNAME lambdaname`
aws logs tail --format short /aws/lambda/$SSMBAK_LAMBDANAME
```

```
2024-06-13T20:11:07 INIT_START Runtime Version: python:3.13.v36	Runtime Version ARN: arn:aws:lambda:us-west-2::runtime:bbd47e5ef4020932b9374e2ab9f9ed3bac502f27e17a031c35d9fb8935cf1f8c
2024-06-13T20:11:07 START RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd Version: $LATEST
2024-06-13T20:11:10 [INFO]	2024-06-13T20:11:10.776Z	d404f4c7-1c53-5e41-a7db-aa2248dee8cd	put_object {'Bucket': 'ssmbak-bucket-vhvs73zpfvy5', 'Key': '/testyssmbak/3', 'Tagging': 'ssmbakTime=1718309456&ssmbakType=String', 'Body': 'initial'}
2024-06-13T20:11:10 [INFO]	2024-06-13T20:11:10.964Z	d404f4c7-1c53-5e41-a7db-aa2248dee8cd	result: 200
2024-06-13T20:11:11 END RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd
2024-06-13T20:11:11 REPORT RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd	Duration: 3430.49 ms	Billed Duration: 3431 ms	Memory Size: 128 MB	Max Memory Used: 84 MB	Init Duration: 282.28 ms
...
```

# Development
This is a [poetry](https://python-poetry.org/) project, so it should
be butter once you get that sorted. Install
[pre-commit](https://pre-commit.com/) for ruff check/format on commit,
mypy on push.

# Testing
Testing uses localstack, as you can see in the [Github
actions](https://github.com/newvoll/ssmbak/actions). `docker compose up ssmbak --detach`, then `poetry run pytest`.

* Recent docker versions allow for `docker-compose up --watch`, allowing for
hot-reloading of the lambda.

* Lambda tests use both the lambda's backup function and hitting the
  local container running it.


## Testing Gotchas
* Tests are pinned to localstack via `tests/safety.py` — boto3 client
  creation raises `RuntimeError` for any non-localstack endpoint. Don't
  disable this; tests will set versioning on the bucket and
  manipulate/destroy `pytest.test_path`.


# Addenda
* `ssmbak-stack` creates two alarms for the process queue, in case
  you'd like to configure some actions.
* Use a custom kms key for added security, which will require you to set up the infra.
* Support for advanced ssm params has not been tested at all.
