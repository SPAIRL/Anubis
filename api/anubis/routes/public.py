import string
from datetime import datetime, timedelta

from flask import request, redirect, Blueprint, make_response

from anubis.models import Assignment, AssignmentRepo
from anubis.models import Submission
from anubis.models import db, User, Class_, InClass
from anubis.utils.auth import current_user
from anubis.utils.auth import get_token
from anubis.utils.cache import cache
from anubis.utils.data import error_response, success_response, is_debug
from anubis.utils.data import fix_dangling
from anubis.utils.data import get_classes, get_assignments, get_submissions
from anubis.utils.data import regrade_submission, enqueue_webhook_rpc
from anubis.utils.decorators import json_response, require_user
from anubis.utils.elastic import log_endpoint, esindex
from anubis.utils.http import get_request_ip
from anubis.utils.logger import logger
from anubis.utils.oauth import OAUTH_REMOTE_APP as provider

public = Blueprint('public', __name__, url_prefix='/public')


@public.route('/login')
@log_endpoint('public-login', lambda: 'login')
def public_login():
    return provider.authorize(
        callback='https://anubis.osiris.services/api/public/oauth'
    )


@public.route('/logout')
@log_endpoint('public-logout', lambda: 'logout')
def public_logout():
    r = make_response(redirect('/'))
    r.set_cookie('token', '')
    return r


@public.route('/oauth')
@log_endpoint('public-oauth', lambda: 'oauth')
def public_oauth():
    next_url = request.args.get('next') or '/courses'
    resp = provider.authorized_response()
    if resp is None or 'access_token' not in resp:
        return 'Access Denied'

    user_data = provider.get('userinfo?schema=openid', token=(resp['access_token'],))

    netid = user_data.data['netid']
    name = user_data.data['firstname'] + ' ' + user_data.data['lastname']

    u = User.query.filter(User.netid == netid).first()
    if u is None:
        u = User(netid=netid, name=name, is_admin=False)
        db.session.add(u)
        db.session.commit()

    if u.github_username is None:
        next_url = '/set-github-username'

    fix_dangling()

    r = make_response(redirect(next_url))
    r.set_cookie('token', get_token(u.netid))

    return r


@public.route('/set-github-username')
@require_user
@log_endpoint('public-set-github-username', lambda: 'github username set')
@json_response
def public_set_github_username():
    u: User = current_user()

    github_username = request.args.get('github_username', default=None)
    if github_username is None:
        return error_response('missing field')
    github_username = github_username.strip()

    if any(i in string.whitespace for i in github_username):
        return error_response('Your username can not have spaces')

    if not (all(i in (string.ascii_letters + string.digits + '-') for i in github_username)
            and not github_username.startswith('-') and not github_username.endswith('-')):
        return error_response('Github usernames may only contain alphanumeric characters '
                              'or single hyphens, and cannot begin or end with a hyphen.')

    logger.info(str(u.last_updated))
    logger.info(str(u.last_updated + timedelta(hours=1)) + ' - ' + str(datetime.now()))

    if u.github_username is not None and u.last_updated + timedelta(hours=1) < datetime.now():
        return error_response('Github usernames can only be '
                              'changed one hour after first setting. '
                              'Email the TAs to reset your github username.')  # reject their github username change

    u.github_username = github_username
    db.session.add(u)
    db.session.commit()

    return success_response(github_username)


@public.route('/classes')
@require_user
@log_endpoint('public-classes', lambda: 'get classes {}'.format(get_request_ip()))
@json_response
def public_classes():
    """
    Get class data for current user

    :return:
    """
    user: User = current_user()
    return success_response({
        'classes': get_classes(user.netid)
    })


@public.route('/assignments')
@require_user
@log_endpoint('public-assignments', lambda: 'get assignments {}'.format(get_request_ip()))
@json_response
def public_assignments():
    """
    Get all the assignments for a user. Optionally specify a class
    name as a get query.

    /api/public/assignments?class=Intro to OS

    :return: { "assignments": [ assignment.data ] }
    """

    # Get optional class filter from get query
    class_name = request.args.get('class', default=None)

    # Load current user
    user: User = current_user()

    # Get (possibly cached) assignment data
    assignment_data = get_assignments(user.netid, class_name)

    # Iterate over assignments, getting their data
    return success_response({
        'assignments': assignment_data
    })


@public.route('/submissions')
@require_user
@log_endpoint('public-submissions', lambda: 'get submissions {}'.format(get_request_ip()))
@json_response
def public_submissions():
    """
    Get all submissions for a given student. Optionally specify class,
    and assignment name filters in get query.


    /api/public/submissions
    /api/public/submissions?class=Intro to OS
    /api/public/submissions?assignment=Assignment 1: uniq
    /api/public/submissions?class=Intro to OS&assignment=Assignment 1: uniq

    :return:
    """
    # Get optional filters
    class_name = request.args.get('class', default=None)
    assignment_name = request.args.get('assignment', default=None)

    # Load current user
    user: User = current_user()

    # Get submissions through cached function
    return success_response({
        'submissions': get_submissions(
            user.netid,
            class_name=class_name,
            assignment_name=assignment_name)
    })


@public.route('/submission/<string:commit>')
@require_user
@log_endpoint('public-submission-commit', lambda: 'get submission {}'.format(request.path))
@json_response
@cache.memoize(timeout=1, unless=is_debug)
def public_submission(commit: str):
    """
    Get submission data for a given commit.

    :param commit:
    :return:
    """
    # Get current user
    user: User = current_user()

    # Try to find commit (verifying ownership)
    s = Submission.query.join(User).filter(
        User.netid == user.netid,
        Submission.commit == commit
    ).first()

    # Make sure we caught one
    if s is None:
        return error_response('Commit does not exist'), 406

    # Hand back submission
    return success_response({'submission': s.full_data})


def webhook_log_msg():
    if request.headers.get('Content-Type', None) == 'application/json' and \
    request.headers.get('X-GitHub-Event', None) == 'push':
        return request.json['pusher']['name']
    return None


@public.route('/memes')
@log_endpoint('rick-roll', lambda: 'rick-roll')
def public_memes():
    logger.info('rick-roll')
    return redirect('https://www.youtube.com/watch?v=dQw4w9WgXcQ&autoplay=1')


@public.route('/regrade/<commit>')
@require_user
@log_endpoint('regrade-request', lambda: 'submission regrade request ' + request.path)
@json_response
def public_regrade_commit(commit=None):
    """
    This route will get hit whenever someone clicks the regrade button on a
    processed assignment. It should do some validity checks on the commit and
    netid, then reset the submission and re-enqueue the submission job.
    """
    if commit is None:
        return error_response('incomplete_request'), 406

    # Load current user
    user: User = current_user()

    # Find the submission
    submission: Submission = Submission.query.join(User).filter(
        Submission.commit == commit,
        User.netid == user.netid
    ).first()

    # Verify Ownership
    if submission is None:
        return error_response('invalid commit hash or netid'), 406

    # Regrade
    return regrade_submission(submission)


# dont think we need GET here
@public.route('/webhook', methods=['POST'])
@log_endpoint('webhook', webhook_log_msg)
@json_response
def public_webhook():
    """
    This route should be hit by the github when a push happens.
    We should take the the github repo url and enqueue it as a job.
    """

    content_type = request.headers.get('Content-Type', None)
    x_github_event = request.headers.get('X-GitHub-Event', None)

    # Verify some expected headers
    if not (content_type == 'application/json' and x_github_event == 'push'):
        return error_response('Unable to verify webhook')

    webhook = request.json

    # Load the basics from the webhook
    repo_url = webhook['repository']['url']
    github_username = webhook['pusher']['name']
    commit = webhook['after']
    assignment_name = webhook['repository']['name'][:-(len(github_username) + 1)]

    # Attempt to find records for the relevant models
    assignment = Assignment.query.filter(
        Assignment.unique_code.in_(webhook['repository']['name'].split('-'))
    ).first()
    user = User.query.filter(User.github_username == github_username).first()

    # The before Hash will be all 0s on for the first hash.
    # We will want to ignore both this first push (the initialization of the repo)
    # and all branches that are not master.
    if webhook['before'] == '0000000000000000000000000000000000000000':
        # Record that a new repo was created (and therefore, someone just started their assignment)
        logger.info('new student repo ', extra={
            'repo_url': repo_url, 'github_username': github_username,
            'assignment_name': assignment_name, 'commit': commit,
        })
        esindex('new-repo', repo_url=repo_url, assignment=str(assignment))
        return success_response('initial commit')

    # Verify that we can match this push to an assignment
    if assignment is None:
        logger.error('Could not find assignment', extra={
            'repo_url': repo_url, 'github_username': github_username,
            'assignment_name': assignment_name, 'commit': commit,
        })
        return error_response('assignment not found'), 406

    repo = AssignmentRepo.query.join(Assignment).join(Class_).join(InClass).join(User).filter(
        User.github_username == github_username,
        Assignment.unique_code == assignment.unique_code,
        AssignmentRepo.repo_url == repo_url,
    ).first()

    logger.debug('webhook data', extra={
        'github_username': github_username, 'assignment': assignment.name,
        'repo_url': repo_url, 'commit': commit, 'unique_code': assignment.unique_code
    })

    if not is_debug():
        # Make sure that the repo we're about to process actually belongs to our organization
        if not webhook['repository']['full_name'].startswith('os3224/'):
            logger.error('Invalid github organization in webhook.', extra={
                'repo_url': repo_url, 'github_username': github_username,
                'assignment_name': assignment_name, 'commit': commit,
            })
            return error_response('invalid repo'), 406

    # if we dont have a record of the repo, then add it
    if repo is None:
        repo = AssignmentRepo(owner=user, assignment=assignment, repo_url=repo_url, github_username=github_username)
        db.session.add(repo)
        db.session.commit()

    if webhook['ref'] != 'refs/heads/master':
        logger.warning('not push to master', extra={
            'repo_url': repo_url, 'github_username': github_username,
            'assignment_name': assignment_name, 'commit': commit,
        })
        return error_response('not push to master')

    # Create a shiny new submission
    submission = Submission(assignment=assignment, repo=repo, owner=user, commit=commit,
                            state='Waiting for resources...')
    db.session.add(submission)
    db.session.commit()

    # Create the related submission models
    submission.init_submission_models()

    # If a user has not given us their github username
    # the submission will stay in a "dangling" state
    if user is None:
        logger.warning('dangling submission from {}'.format(github_username), extra={
            'repo_url': repo_url, 'github_username': github_username,
            'assignment_name': assignment_name, 'commit': commit,
        })
        esindex(
            type='error',
            logs='dangling submission by: ' + github_username,
            submission=submission.data,
            neitd=None,
        )
        return error_response('dangling submission')

    # Log the submission
    esindex(
        index='submission',
        processed=0,
        error=-1,
        passed=-1,
        netid=submission.netid,
        commit=submission.commit,
    )

    # if the github username is not found, create a dangling submission
    enqueue_webhook_rpc(submission.id)

    return success_response('submission accepted')


@public.route('/whoami')
def public_whoami():
    """
    Figure out who you are

    :return:
    """
    u: User = current_user()
    if u is None:
        return success_response(None)
    return success_response({
        'user': u.data,
        'classes': get_classes(u.netid),
        'assignments': get_assignments(u.netid),
    })