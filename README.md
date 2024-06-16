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
from ssmbak.restore.actions import Path
Path.restore()
```

# Quickstart
You'll need the awscli and credentials that can create IAM resources
with Cloudformation (to assign minimal permissions to the lambda
role).

```
pip install ssmbak
ssmbak-stack <SSMBAK_STACKNAME> create
```

That's it. All new params will automatically be backed-up and
available for `ssmbak` point-in-time restore via CLI or lib, like:

`ssmbak preview /my/ssm/path/ 2024-06-15T17:56:58`


# CLI Tutorial

```
SSMBAK_STACKNAME=ssmbak
ssmbak-stack $SSMBAK_STACKNAME create
```

```
06/15/24 17:25:25   CREATE_IN_PROGRESS  ssmbak  AWS::CloudFormation::Stack  User Initiated
...
06/15/24 17:26:44   CREATE_COMPLETE  ssmbak  AWS::CloudFormation::Stack
```

Once the stack is up and new params are backed-up automatically, you can go through the following steps to give you a feel for how it works.

Create some params with value `initial` in `/testyssmbak/` and `/testyssmbak/deeper` to show recursion. We'll also set key `/testyssmbak` to show the difference between keys and paths.

```
aws ssm put-parameter --name /testyssmbak --value initial --type String --overwrite
for i in $(seq 3)
do
aws ssm put-parameter --name /testyssmbak/$i --value initial --type String --overwrite
aws ssm put-parameter --name /testyssmbak/deeper/$i --value initial --type String --overwrite
done
```

```
Standard        1
Standard        1
Standard        1
Standard        1
Standard        1
Standard        1
Standard        1
```

Sleep a bit to give EventBridge some time to process the event, mark
it (UTC), and sleep some more to give ssmbak some time to back them
up.

```
sleep 30
IN_BETWEEN=`date -u +"%Y-%m-%dT%H:%M:%S"`
sleep 30
```

They're all set to `inital`.

```
aws ssm get-parameters-by-path --path /testyssmbak --recursive \
  | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";'
```

```
/testyssmbak/1 		 initial
/testyssmbak/2 		 initial
/testyssmbak/3 		 initial
/testyssmbak/deeper/1 		 initial
/testyssmbak/deeper/2 		 initial
/testyssmbak/deeper/3 		 initial
```


Update #2 for path and subpath:

```
aws ssm put-parameter --name /testyssmbak/2 --value UPDATED --type String --overwrite
aws ssm put-parameter --name /testyssmbak/deeper/2 --value UPDATED --type String --overwrite
```

```
Standard        2
Standard        2
```


Let's sleep a bit before marking the time. Then we see that
#2 for each is set to `UPDATED`:

```
sleep 30
UPDATED_MARK=`date -u +"%Y-%m-%dT%H:%M:%S"`
aws ssm get-parameters-by-path --path /testyssmbak --recursive \
  | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";'
```

```
/testyssmbak/1 		 initial
/testyssmbak/2 		 UPDATED
/testyssmbak/3 		 initial
/testyssmbak/deeper/1 		 initial
/testyssmbak/deeper/2 		 UPDATED
/testyssmbak/deeper/3 		 initial
```


When we preview the IN_BETWEEN point-in-time, we see that everything
was `initial` at that time.

> [!NOTE]
> Paths end with a slash, which is why key `/testyssmbak` doesn't show
> up in the previews.

```
ssmbak preview /testyssmbak/ $IN_BETWEEN --recursive
```

```
+-----------------------+---------+--------+---------------------------+
| Name                  | Value   | Type   | Modified                  |
+-----------------------+---------+--------+---------------------------+
| /testyssmbak/1        | initial | String | 2024-06-15 17:48:58+00:00 |
| /testyssmbak/2        | initial | String | 2024-06-15 17:49:00+00:00 |
| /testyssmbak/3        | initial | String | 2024-06-15 17:49:01+00:00 |
| /testyssmbak/deeper/1 | initial | String | 2024-06-15 17:48:59+00:00 |
| /testyssmbak/deeper/2 | initial | String | 2024-06-15 17:49:00+00:00 |
| /testyssmbak/deeper/3 | initial | String | 2024-06-15 17:49:02+00:00 |
+-----------------------+---------+--------+---------------------------+
```

Do the restore:

```
ssmbak restore /testyssmbak/ $IN_BETWEEN --recursive
```

```
+-----------------------+---------+--------+---------------------------+
| Name                  | Value   | Type   | Modified                  |
+-----------------------+---------+--------+---------------------------+
| /testyssmbak/1        | initial | String | 2024-06-15 17:48:58+00:00 |
| /testyssmbak/2        | initial | String | 2024-06-15 17:49:00+00:00 |
| /testyssmbak/3        | initial | String | 2024-06-15 17:49:01+00:00 |
| /testyssmbak/deeper/1 | initial | String | 2024-06-15 17:48:59+00:00 |
| /testyssmbak/deeper/2 | initial | String | 2024-06-15 17:49:00+00:00 |
| /testyssmbak/deeper/3 | initial | String | 2024-06-15 17:49:02+00:00 |
+-----------------------+---------+--------+---------------------------+
```


And now they're all back to `initial`:

```
aws ssm get-parameters-by-path --path /testyssmbak --recursive \
  | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";'
```

```
/testyssmbak/1 		 initial
/testyssmbak/2 		 initial
/testyssmbak/3 		 initial
/testyssmbak/deeper/1 		 initial
/testyssmbak/deeper/2 		 initial
/testyssmbak/deeper/3 		 initial
```


Let's say we made a mistake and want to revert one of the UPDATED keys:

```
ssmbak preview /testyssmbak/deeper/2 $UPDATED_MARK --recursive
```
```
+-----------------------+---------+--------+---------------------------+
| Name                  | Value   | Type   | Modified                  |
+-----------------------+---------+--------+---------------------------+
| /testyssmbak/deeper/2 | UPDATED | String | 2024-06-15 16:38:24+00:00 |
+-----------------------+---------+--------+---------------------------+
```

And restore:

```
ssmbak restore /testyssmbak/deeper/2 $UPDATED_MARK
```
```
+-----------------------+---------+--------+---------------------------+
| Name                  | Value   | Type   | Modified                  |
+-----------------------+---------+--------+---------------------------+
| /testyssmbak/deeper/2 | UPDATED | String | 2024-06-15 16:38:24+00:00 |
+-----------------------+---------+--------+---------------------------+
```

Voila. Just `/testyssmbak/deeper/2` is `UPDATED`.

```
aws ssm get-parameters-by-path --path /testyssmbak --recursive \
  | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";'
```
```
/testyssmbak/1 		 initial
/testyssmbak/2 		 initial
/testyssmbak/3 		 initial
/testyssmbak/deeper/1 		 initial
/testyssmbak/deeper/2 		 UPDATED
/testyssmbak/deeper/3 		 initial
```

Let's mark the time and clean up our SSM tree:

```
END_MARK=`date -u +"%Y-%m-%dT%H:%M:%S"`
aws ssm get-parameters-by-path --path /testyssmbak --recursive \
  | perl -ne '@h=split; print "$h[4] ";' \
  | xargs aws ssm delete-parameters --names
sleep 30
```
```
DELETEDPARAMETERS       /testyssmbak
DELETEDPARAMETERS       /testyssmbak/1
DELETEDPARAMETERS       /testyssmbak/2
DELETEDPARAMETERS       /testyssmbak/3
DELETEDPARAMETERS       /testyssmbak/deeper/1
DELETEDPARAMETERS       /testyssmbak/deeper/2
DELETEDPARAMETERS       /testyssmbak/deeper/3
```

And pretend we made a mistake. Oh no! We want them all back. Let's give ssmbak some time to process and see what we can restore.

```
sleep 30
ssmbak preview /testyssmbak/ $END_MARK --recursive
```
```
+-----------------------+---------+--------+---------------------------+
| Name                  | Value   | Type   | Modified                  |
+-----------------------+---------+--------+---------------------------+
| /testyssmbak/1        | initial | String | 2024-06-15 17:34:37+00:00 |
| /testyssmbak/2        | initial | String | 2024-06-15 17:34:37+00:00 |
| /testyssmbak/3        | initial | String | 2024-06-15 17:34:37+00:00 |
| /testyssmbak/deeper/1 | initial | String | 2024-06-15 17:34:37+00:00 |
| /testyssmbak/deeper/2 | UPDATED | String | 2024-06-15 17:35:27+00:00 |
| /testyssmbak/deeper/3 | initial | String | 2024-06-15 17:34:37+00:00 |
+-----------------------+---------+--------+---------------------------+
```

We won't do the restore after all and stay cleaned-up.

In all this we haven't seen or touched the key `/testyssmbak`, which
differs from path `/testyssmbak/`.

```
ssmbak preview /testyssmbak `date -u +"%Y-%m-%dT%H:%M:%S"`
```

```
+--------------+---------+--------+---------------------------+
| Name         | Value   | Type   | Modified                  |
+--------------+---------+--------+---------------------------+
| /testyssmbak | initial | String | 2024-06-15 20:55:47+00:00 |
+--------------+---------+--------+---------------------------+
```

versus:

```
ssmbak preview /testyssmbak/ `date -u +"%Y-%m-%dT%H:%M:%S"`
```
```
+----------------+---------+--------+---------------------------+
| Name           | Value   | Type   | Modified                  |
+----------------+---------+--------+---------------------------+
| /testyssmbak/1 | initial | String | 2024-06-15 21:01:55+00:00 |
| /testyssmbak/2 | initial | String | 2024-06-15 21:01:55+00:00 |
| /testyssmbak/3 | initial | String | 2024-06-15 21:01:55+00:00 |
+----------------+---------+--------+---------------------------+
```


### CLI Gotchas:
* You need a bunch of shady permissions to create the stack. Look for
  such errors if it fails.
* `aws` commands require that the awscli is installed and configured.


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
2024-06-13T20:11:07 INIT_START Runtime Version: python:3.10.v36	Runtime Version ARN: arn:aws:lambda:us-west-2::runtime:bbd47e5ef4020932b9374e2ab9f9ed3bac502f27e17a031c35d9fb8935cf1f8c
2024-06-13T20:11:07 START RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd Version: $LATEST
2024-06-13T20:11:10 [INFO]	2024-06-13T20:11:10.776Z	d404f4c7-1c53-5e41-a7db-aa2248dee8cd	put_object {'Bucket': 'ssmbak-bucket-vhvs73zpfvy5', 'Key': '/testyssmbak/3', 'Tagging': 'ssmbakTime=1718309456&ssmbakType=String', 'Body': 'initial'}
2024-06-13T20:11:10 [INFO]	2024-06-13T20:11:10.964Z	d404f4c7-1c53-5e41-a7db-aa2248dee8cd	result: 200
2024-06-13T20:11:11 END RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd
2024-06-13T20:11:11 REPORT RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd	Duration: 3430.49 ms	Billed Duration: 3431 ms	Memory Size: 128 MB	Max Memory Used: 84 MB	Init Duration: 282.28 ms
...
```

# Lib Tutorial

Use the cli to get the bucketname, or check the stack resources with your preferred method.
```
ssmbak-stack ssmbak bucketname
```
```
ssmbak-bucket-dkvp9oegrx2y
```

Session:
```
>>> from ssmbak.restore.actions import Path
>>> from datetime import datetime, timezone
>>> in_between = datetime.strptime("2024-06-13T01:55:26", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
>>> path = Path("/testoossmbak", in_between, "us-west-2", "ssmbak-bucket-dkvp9oegrx2y", recurse=True)
>>> path.preview()
[{'Name': '/testoossmbak/deep/yay', 'Deleted': True, 'Modified': datetime.datetime(2024, 6, 13, 1, 50, 22, tzinfo=tzutc())}]
>>> path.restore()
```

# Development
This is a [poetry](https://python-poetry.org/) project, so it should
be butter once you get that sorted. Install
[pre-commit](https://pre-commit.com/) for black on commit, lint and
typing on push.

# Testing
Testing uses localstack, as you can see in the [Github
actions](https://github.com/newvoll/ssmbak/actions). `docker-compose up` should do the trick, then `./tests/test_localstack.sh`.

* `source tests/localstack_env.sh` to point ssmbak to localstack.

* Recent docker versions allow for `docker-compose up --watch`, allowing for
hot-reloading of the lambda.

* Lambda tests use both the lambda's backup function and hitting the
  local container running it. Container tests are skipped in AWS.


## Testing Gotchas
* When testing on aws instead of localstack, don't use same bucket as running lambda!
  * The lambda will be processing and backing up in addition to the tests.
  * Tests will set versioning on the bucket and manipulate/destroy pytest.test_path.


# Addenda
* `ssmbak-stack` creates two alarms for the process queue, in case
  you'd like to configure some actions.
* Use a custom kms key for added security, which will require you to set up the infra.
* Support for advanced ssm params has not been tested at all.
