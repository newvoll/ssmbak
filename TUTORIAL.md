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
>>> from ssmbak.restore.actions import ParamPath
>>> from datetime import datetime, timezone
>>> in_between = datetime.strptime("2024-06-13T01:55:26", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
>>> path = ParamPath("/testoossmbak", in_between, "us-west-2", "ssmbak-bucket-dkvp9oegrx2y", recurse=True)
>>> path.preview()
[{'Name': '/testoossmbak/deep/yay', 'Deleted': True, 'Modified': datetime.datetime(2024, 6, 13, 1, 50, 22, tzinfo=tzutc())}]
>>> path.restore()
```

# CLI Tutorial

You'll need the [awcli](https://aws.amazon.com/cli/) unless you want
to point and click in the AWS management console to follow along.

> [!WARNING]
> There are sleeps in between steps to give SQS -> Lambda time to process. If AWS is slow, you might have to wait longer.

First, create the stack.

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
sleep 120
IN_BETWEEN=`date -u +"%Y-%m-%dT%H:%M:%S"`
sleep 120
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
sleep 120
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
> ParamPaths end with a slash, which is why key `/testyssmbak` doesn't show
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
sleep 120
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
sleep 120
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
