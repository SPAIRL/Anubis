import time

from kubernetes import config, client

from anubis.models import db, Config, TheiaSession
from anubis.utils.data import with_context
from anubis.utils.k8s.theia import (
    update_theia_pod_cluster_addresses,
    fix_stale_theia_resources,
    create_theia_k8s_pod_pvc,
    reap_old_theia_sessions,
    reap_theia_session,
    list_theia_pods,
)
from anubis.utils.lms.theia import get_theia_pod_name
from anubis.utils.services.logger import logger


@with_context
def initialize_theia_session(theia_session_id: str):
    """
    Create the kube resources for a theia session. Will update
    database entry to reflect that the session has been initialized.

    After creating the theia session kubernetes resources, this
    function will wait up to 60 seconds for the session resources
    to come out of "Pending". We do this so that we can capture the
    pod cluster ip address. Without setting this IP address, there
    is no way for the theia proxy to direct traffic to the session.
    If it reaches 60 seconds, we cut our loses and return. The reaper
    job that fires every 5 minutes will be on the lookout for sessions
    that have been initialized but are missing cluster ip addresses
    and update them accordingly.

    :param theia_session_id:
    :return:
    """

    # Load the kubernetes incluster config
    config.load_incluster_config()
    v1 = client.CoreV1Api()

    # Log the initialization event
    logger.info(
        "Initializing theia session {}".format(theia_session_id),
        extra={
            "Initializing theia session": theia_session_id,
        },
    )

    # Calculate the maximum IDEs that are allowed to exist at any given time
    max_ides = Config.query.filter(Config.key == "MAX_IDES").first()
    max_ides = int(max_ides.value) if max_ides is not None else 10

    # Check to ses how many theia sessions are marked as active in the database. If that
    # count exceeds the artificial limit of IDEs, then we need to re-enqueue this job.
    if TheiaSession.query.filter(
            TheiaSession.active == True,
            TheiaSession.state != 'Initializing',
    ).count() >= max_ides:
        from anubis.utils.services.rpc import enqueue_ide_initialize

        # If there are too many active pods, recycle the job through the queue.
        logger.info(
            "Maximum IDEs currently running. Re-enqueuing session_id={} initialized request".format(
                theia_session_id
            )
        )

        # Re-enqueue this initialization job, then return
        enqueue_ide_initialize(theia_session_id)
        return

    # Get the theia session
    theia_session = TheiaSession.query.filter(
        TheiaSession.id == theia_session_id,
    ).first()

    # Confirm that the theia session exists.
    if theia_session is None:
        # Log the error if there was one, then return
        logger.error(
            "Unable to find theia session rpc.initialize_theia_session",
            extra={"theia_session_id": theia_session_id},
        )
        return

    # Log the event
    logger.info(
        "Found theia_session to init {}".format(theia_session_id),
        extra={"submission": theia_session.data},
    )

    # Create pod, and pvc object from the options specified for the
    # theia session.
    pod, pvc = create_theia_k8s_pod_pvc(theia_session)

    # Log the creation of the pod
    logger.info("creating theia pod: " + pod.to_str())

    # Send the pvc and pod to the kubernetes api. Ask to create
    # these resources under the anubis namespace. These actions are by default
    # backgrounded. That means that these functions will almost certainly return
    # before the resources have actually been created and initialized.
    v1.create_namespaced_persistent_volume_claim(namespace="anubis", body=pvc)
    v1.create_namespaced_pod(namespace="anubis", body=pod)

    # Get the name of the pod we just created
    name = get_theia_pod_name(theia_session)

    # Wait for the theia session to have started,
    # then update theia_session state.
    n = 10
    while True:

        # Get the pod information from the kubernetes api
        pod: client.V1Pod = v1.read_namespaced_pod(
            namespace="anubis", name=name,
        )

        # If the pod is pending still, then iterate
        # the n and continue. The pod is pending while
        # the main containers have not started.
        if pod.status.phase == "Pending":

            # Wait at 60 iterations while it is pending before giving up
            n += 1
            if n > 60:
                logger.error(
                    "Theia session took too long to initialize. Freeing worker."
                )
                break

            # Sleep one second before iterating
            time.sleep(1)

        # If the pod is marked as running. The pod is marked as
        # running when the main containers have started. In practice,
        # the theia server still does take a few moments to start
        # after the pod is marked as running. We can introduce a small
        # amount of delay at this step to make sure we don't give a user
        # the "goto ide" button before the ide has actually started
        if pod.status.phase == "Running":
            # Set the cluster address and state
            theia_session.cluster_address = pod.status.pod_ip
            theia_session.state = "Running"

            # We need to introduce a small amount of time here
            # to give the theia server a moment to actually run
            # before the button on the web frontend to go to
            # the session is available to the user.
            time.sleep(1)

            # Index the event
            logger.info(
                "theia",
                extra={
                    "event": "session-init",
                    "session_id": theia_session.id,
                    "netid": theia_session.owner.netid,
                },
            )

            # Log the event
            logger.info("Theia session started {}".format(name))
            break

        # If the pod has failed. There are more than a few ways that
        # the pod could have failed. If we reach this, then we should
        # just mark the theia session as failed, then let the reaper
        # job clean up the kubernetes resources at a later date.
        if pod.status.phase == "Failed":
            # Mark the theia session as inactive and failed
            theia_session.active = False
            theia_session.state = "Failed"

            # Log the error
            logger.error("Theia session failed {}".format(name))
            break

    # Commit any and all changes that have been made
    # in the database up to this point.
    db.session.commit()


@with_context
def reap_theia_session_by_id(theia_session_id: str):
    """
    Reap the theia session identified by id. This will mark the theia
    session resources in kubernetes for deletion, then mark the database
    entry for the session as inactive.

    :param theia_session_id:
    :return:
    """

    # Load incluster kubernetes config
    config.load_incluster_config()

    # Log the reap
    logger.info("Attempting to reap theia session {}".format(theia_session_id))

    # Find the theia session in the database
    theia_session: TheiaSession = TheiaSession.query.filter(
        TheiaSession.id == theia_session_id,
    ).first()

    # Make sure that we have a record for this session
    if theia_session is None:
        logger.error(
            "Could not find theia session {} when attempting to delete".format(
                theia_session_id
            )
        )
        return

    # Reap the session
    reap_theia_session(theia_session)


@with_context
def reap_theia_sessions_in_course(course_id: str):
    """
    Reap all theia sessions within a specific course. This will
    kick everyone off their IDEs.

    There may be many database entries that this function updates
    so we will batch commits to help speed things up, while
    keeping things relatively consistent in the cluster.

    :param course_id:
    :return:
    """

    # Load the incluster config
    config.load_incluster_config()

    # Lof the reap
    logger.info(f"Clearing theia sessions course_id={course_id}")

    # Find all theia sessions in the database that are
    # marked as active.
    theia_sessions = TheiaSession.query.filter(
        TheiaSession.active == True,
        TheiaSession.course_id == course_id,
    ).all()

    # Iterate through all active theia sessions in the database, deleting and
    # updating as we go.
    for n, theia_session in enumerate(theia_sessions):
        # Reap the session
        reap_theia_session(theia_session, commit=False)

        # Batch commits in size of 5
        if n % 5 == 0:
            db.session.commit()

    db.session.commit()


@with_context
def reap_stale_theia_sessions(*_):
    """
    Reap any and all stale sessions either in the database or
    in kubernetes. This function should be run periodically in
    the reap job to ensure that the state in the database matches
    what is running in the cluster and vice versa.

    :param _:
    :return:
    """

    # Log the event
    logger.info("Clearing stale theia sessions")

    # Get the list of active pods
    theia_pods = list_theia_pods()

    # Update the records for pod ip addresses
    update_theia_pod_cluster_addresses(theia_pods)

    # Check that all theia sessions have not
    # reached the global timeout.
    reap_old_theia_sessions(theia_pods)

    # Make sure that database entries marked
    # as active have pods and pods have active
    # database entries.
    fix_stale_theia_resources(theia_pods)

    db.session.commit()