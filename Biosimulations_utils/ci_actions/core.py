""" Utilies for CI workflows for reviewing and committing simulators to the BioSimulators registry

:Author: Jonathan Karr <karr@mssm.edu>
:Date: 2020-10-20
:Copyright: 2020, Center for Reproducible Biomedical Modeling
:License: MIT
"""

import functools
import io
import os
import requests
import types
import yamldown


class ActionCaughtError(Exception):
    pass


class ActionErrorHandling(object):
    @classmethod
    def catch_errors(cls, issue_number, error_msg='Sorry. We encountered an unexpected error. Our team will review the error.'):
        """ Generator for a decorator for CI actions that catches errors and reports them as comments to an issue

        Args:
            issue_number (:obj:`str`): issue number
            error_msg (:obj:`str`, optional): error message to display to users
        """
        return functools.partial(cls._catch_errors, issue_number, error_msg)

    @classmethod
    def _catch_errors(cls, issue_number, error_msg, func):
        """ Decorator for CI actions that catches errors and reports them as comments to an issue

        Args:
            issue_number (:obj:`str`): issue number
            error_msg (:obj:`str`): error message to display to users
            func (:obj:`types.FunctionType`): decorated function
        """
        try:
            func()
        except ActionCaughtError:
            raise
        except Exception as error:
            Action.add_error_comment_to_issue(issue_number, error_msg)
            Action.add_labels_to_issue(issue_number, ['Action error'])
            raise


class Action(object):
    """ A continuous integration action

    Attributes:
        gh_auth
        gh_repo (:obj:`str`): owner and name of the repository which triggered the action
        gh_action_run_id (:obj:`str`): GitHub action run id
        gh_action_run_url (:obj:`str`): URL for the GitHub action run
    """
    GH_ACTION_RUN_URL = 'https://github.com/{}/actions/runs/{}'
    ISSUE_ENDPOINT = 'https://api.github.com/repos/biosimulators/Biosimulators/issues/{}'
    ISSUE_COMMENTS_ENDPOINT = 'https://api.github.com/repos/biosimulators/Biosimulators/issues/{}/comments'
    ISSUE_LABELS_ENDPOINT = 'https://api.github.com/repos/biosimulators/Biosimulators/issues/{}/labels'

    def __init__(self):
        self.gh_auth = self.get_gh_auth()
        self.gh_repo = self.get_gh_repo()
        self.gh_action_run_id = self.get_gh_action_run_id()
        self.gh_action_run_url = self.GH_ACTION_RUN_URL.format(self.gh_repo, self.gh_action_run_id)

    @ActionErrorHandling.catch_errors
    def run(self):
        pass

    @staticmethod
    def get_gh_repo():
        """ Get the owner and name of the repository which triggered the action

        Returns:
            :obj:`str`: owner and name of the repository which triggered the action
        """
        return os.getenv('GH_REPO')

    @staticmethod
    def get_issue_number():
        """ Get the number of the issue which triggered the action

        Returns:
            :obj:`str`: issue number
        """
        return os.getenv('GH_ISSUE_NUMBER')

    @classmethod
    def get_issue(self, issue_number):
        """ Get the properties of the GitHub issue for the submission

        Args:
            issue_number (:obj:`str`): issue number

        Returns:
            :obj:`dict`: properties of the GitHub issue for the submission
        """
        response = requests.get(
            self.ISSUE_ENDPOINT.format(issue_number),
            auth=self.gh_auth)
        response.raise_for_status()
        return response.json()

    @classmethod
    def get_data_in_issue(self, issue):
        """ Get the YAML-structured data in an issue

        Args:
           issue (:obj:`dict`): properties of the GitHub issue for the submission

        Returns:
            :obj:`object`: YAML-structured data in an issue
        """
        body = io.StringIO(issue['body'].replace('\r', ''))
        data, _ = yamldown.load(body)
        return data

    @classmethod
    def get_labels_for_issue(self, issue_number):
        """ Get the labels for an issue

        Args:
            issue_number (:obj:`str`): issue number

        Returns:
            :obj:`list` of :obj:`str`: labels
        """
        response = requests.get(
            self.ISSUE_LABELS_ENDPOINT.format(issue_number),
            auth=self.gh_auth)
        response.raise_for_status()
        return list([label.name for label in response.json()])

    @classmethod
    def add_labels_to_issue(self, issue_number, labels):
        """ Add one or more labels to an issue

        Args:
            issue_number (:obj:`str`): issue number
            labels (:obj:`list` of :obj:`str`): labels to add to the issue
        """
        response = requests.post(
            self.ISSUE_LABELS_ENDPOINT.format(issue_number),
            auth=self.gh_auth,
            json={'labels': labels})
        response.raise_for_status()

    @classmethod
    def remove_label_from_issue(self, issue_number, label):
        """ Remove a label from an issue

        Args:
            issue_number (:obj:`str`): issue number
            label (:obj:`str`): labels to add to the issue
        """
        response = requests.delete(
            self.ISSUE_LABELS_ENDPOINT.format(issue_number) + '/' + label,
            auth=self.gh_auth)
        response.raise_for_status()

    @classmethod
    def add_comment_to_issue(self, issue_number, comment):
        """ Post a comment to the GitHub issue

        Args:
            issue_number (:obj:`str`): issue number
            comment (:obj:`str`): comment
        """
        response = requests.post(
            self.ISSUE_COMMENTS_ENDPOINT.format(issue_number),
            headers={'accept': 'application/vnd.github.v3+json'},
            auth=self.gh_auth,
            json={'body': comment})
        response.raise_for_status()

    @classmethod
    def add_error_comment_to_issue(self, issue_number, comment):
        """ Post an error to the GitHub issue

        Args:
            issue_number (:obj:`str`): issue number
            comment (:obj:`str`): comment

        Raises:
            :obj:`ValueError`
        """
        self.add_comment_to_issue(issue_number, ''.join([
            '```diff\n',
            '- ' + comment.rstrip().replace('\n', '\n- ') + '\n',
            '```\n',
        ]))
        raise ActionCaughtError(comment)

    @classmethod
    def close_issue(self, issue_number):
        """ Close a GitHub issue 

        Args:
            issue_number (:obj:`str`): issue number
        """
        response = requests.patch(
            self.ISSUE_ENDPOINT.format(issue_number),
            auth=self.gh_auth,
            json={'state': 'closed'})
        response.raise_for_status()

    @staticmethod
    def get_gh_action_run_id():
        """ Get the id for the current GitHub action run

        Returns:
            :obj:`str`: GitHub action run id
        """
        return os.getenv('GH_ACTION_RUN_ID')

    @staticmethod
    def get_gh_auth():
        """ Get authorization for GitHub

        Returns:
            :obj:`dict`: authorization for GitHub
        """
        user = os.getenv('GH_ISSUES_USER')
        access_token = os.getenv('GH_ISSUES_ACCESS_TOKEN')
        return (user, access_token)
