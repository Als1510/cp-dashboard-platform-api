import json
import logging
import re
import requests
from requests_html import HTMLSession
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _log_diagnostic(platform, operation, url, username, response=None,
                                        request_succeeded=True, **details):
    final_url = getattr(response, 'url', url) if response is not None else url
    diagnostic = {
            'platform': platform,
            'operation': operation,
            'upstream_host': url.split('/')[2] if '://' in url else None,
            'final_url': final_url.replace(username, '<redacted>')
            if username else final_url,
            'http_status': getattr(response, 'status_code', None),
            'content_type': getattr(response, 'headers', {}).get('Content-Type')
            if response is not None else None,
            'request_succeeded': request_succeeded,
    }
    diagnostic.update(details)
    if diagnostic.get('failure_category') is None \
            and diagnostic['http_status'] is not None \
            and diagnostic['http_status'] >= 400:
        diagnostic['failure_category'] = 'UPSTREAM_HTTP_FAILURE'
    logger.warning('platform_diagnostic %s', diagnostic)

class UsernameError(Exception):
  pass

class PlatformError(Exception):
  pass

class BrokenChangesError(Exception):
  pass


class StructureError(BrokenChangesError):
    pass


class UpstreamError(Exception):
    def __init__(self, platform, operation, url, message, status_code=None,
                             username_lookup=False, cause=None):
        super().__init__(message)
        self.platform = platform
        self.operation = operation
        self.url = url
        self.message = message
        self.status_code = status_code
        self.username_lookup = username_lookup
        self.cause = cause

    @property
    def public_message(self):
        return self.message


class UpstreamMissingError(UpstreamError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, message='Upstream resource not found', **kwargs)

    @property
    def public_message(self):
        if self.username_lookup:
            return 'Invalid username'
        return self.message


class UpstreamAccessError(UpstreamError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, message='Upstream access failure', **kwargs)


class UpstreamRateLimitError(UpstreamError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, message='Upstream rate limited', **kwargs)


class UpstreamServerError(UpstreamError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, message='Upstream server failure', **kwargs)


class UpstreamTransportError(UpstreamError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, message='Upstream transport failure', **kwargs)


def _validate_upstream_response(response, platform, operation, url,
                                                                username_lookup=False):
    status_code = response.status_code
    error_args = {
            'platform': platform,
            'operation': operation,
            'url': url,
            'status_code': status_code,
            'username_lookup': username_lookup,
    }
    if status_code == 404:
        raise UpstreamMissingError(**error_args)
    if status_code == 403:
        raise UpstreamAccessError(**error_args)
    if status_code == 429:
        raise UpstreamRateLimitError(**error_args)
    if status_code >= 500:
        raise UpstreamServerError(**error_args)
    if status_code >= 400:
        raise UpstreamError(message='Upstream HTTP failure', **error_args)
    return response


def _request_get(url, platform, operation, username_lookup=False):
    try:
        response = requests.get(url)
    except requests.exceptions.RequestException as error:
        raise UpstreamTransportError(
                platform=platform, operation=operation, url=url,
                username_lookup=username_lookup, cause=error)
    return _validate_upstream_response(
            response, platform, operation, url, username_lookup)


def _request_post(url, platform, operation, username_lookup=False, **kwargs):
    try:
        response = requests.post(url=url, **kwargs)
    except requests.exceptions.RequestException as error:
        raise UpstreamTransportError(
                platform=platform, operation=operation, url=url,
                username_lookup=username_lookup, cause=error)
    return _validate_upstream_response(
            response, platform, operation, url, username_lookup)

def get_safe_nested_key(keys, dictionary):
  if not isinstance(dictionary, dict):
      return None
  if isinstance(keys, str):
      return dictionary.get(keys)
  if isinstance(keys, list):
    if len(keys) == 1:
        return dictionary.get(keys[0])
    if len(keys) > 1:
      return get_safe_nested_key(keys[1:], dictionary.get(keys[0]))
    return None
  return None
  
class UserData:
  def __init__(self, username=None):
    self.__username = username

  
  def __codechef(self):
    url = 'https://www.codechef.com/users/{}'.format(self.__username)
    page = _request_get(url, 'codechef', 'profile', username_lookup=True)
    _log_diagnostic('codechef', 'profile', url, self.__username, page,
                    expected_gate='rating-number')
    soup = BeautifulSoup(page.text, 'html.parser')
    try:
        rating_element = soup.find('div', class_='rating-number')
        _log_diagnostic('codechef', 'profile_parser', url, self.__username,
                        page,
                        expected_selector_present=rating_element is not None,
                        parser_stage='rating_gate')
        rating = rating_element.text
    except AttributeError:
        _log_diagnostic('codechef', 'profile_parser', url, self.__username,
                        page, expected_selector_present=False,
                        parser_stage='rating_gate',
                        failure_category='EXPECTED_SELECTOR_MISSING')
        raise StructureError('CodeChef rating selector missing')
    stars = soup.find('span', class_='rating')
    if stars:
        stars = stars.text
    highest_rating_container = soup.find('div', class_='rating-header')
    highest_rating = highest_rating_container.find_next('small').text.split()[-1].rstrip(')')
    rating_ranks_container = soup.find('div', class_='rating-ranks')
    rating_ranks = rating_ranks_container.find_all('a')
    global_rank = rating_ranks[0].strong.text
    country_rank = rating_ranks[1].strong.text
    if global_rank != 'NA':
        global_rank = int(global_rank)
        country_rank = int(country_rank)
    
    def contest_rating_details_get():
        start_ind = page.text.find('[', page.text.find('all_rating'))
        end_ind = page.text.find(']', start_ind) + 1
        next_opening_brack = page.text.find('[', start_ind + 1)
        while next_opening_brack < end_ind:
            end_ind = page.text.find(']', end_ind + 1) + 1
            next_opening_brack = page.text.find('[', next_opening_brack + 1)
        all_rating = json.loads(page.text[start_ind: end_ind])
        for rating_contest in all_rating:
            rating_contest.pop('color')
        return all_rating

    def problems_solved_get():
        problem_solved_section = soup.find('section', class_='rating-data-section problems-solved')
        no_solved = problem_solved_section.find_all('h5')
        categories = problem_solved_section.find_all('article')
        fully_solved = {'count': int(re.findall(r'\d+', no_solved[0].text)[0])}
        if fully_solved['count'] != 0:
            for category in categories[0].find_all('p'):
                category_name = category.find('strong').text[:-1]
                fully_solved[category_name] = []
                for prob in category.find_all('a'):
                    fully_solved[category_name].append({'name': prob.text, 'link': 'https://www.codechef.com' + prob['href']})
        partially_solved = {'count': int(re.findall(r'\d+', no_solved[1].text)[0])}
        if partially_solved['count'] != 0:
            for category in categories[1].find_all('p'):
                category_name = category.find('strong').text[:-1]
                partially_solved[category_name] = []
                for prob in category.find_all('a'):
                    partially_solved[category_name].append({'name': prob.text,'link': 'https://www.codechef.com' + prob['href']})
        return fully_solved, partially_solved

    def user_details_get():
        user_details_attribute_exclusion_list = {'username', 'link', 'teams list', 'discuss profile'}
        header_containers = soup.find_all('header')
        name = header_containers[1].find('h1', class_="h2-style").text
        image = header_containers[1].find('img')['src']
        user_details_section = soup.find('section', class_='user-details')
        user_details_list = user_details_section.find_all('li')
        user_details_response = {'name': name, 'username': user_details_list[0].text.split('★')[-1].rstrip('\n'), 'image': image}
        for user_details in user_details_list:
            attribute, value = user_details.text.split(':')[:2]
            attribute = attribute.strip().lower()
            value = value.strip()
            if attribute not in user_details_attribute_exclusion_list:
                user_details_response[attribute] = value

        return user_details_response

    full, partial = problems_solved_get()
    details = {'status': 'OK', 'rating': int(rating), 'stars': stars, 'highest_rating': int(highest_rating),
                'global_rank': global_rank, 'country_rank': country_rank,
                'user_details': user_details_get(), 
                'contest_ratings': contest_rating_details_get(), 
                'fully_solved': full, 'partially_solved': partial}
    return details

  def __codeforces(self):
    url1 = 'https://codeforces.com/api/user.info?handles={}'.format(self.__username)
    url2 = 'https://codeforces.com/api/user.rating?handle={}'.format(self.__username)
    page1 = _request_get(url1, 'codeforces', 'user.info',
                         username_lookup=True)
    _log_diagnostic('codeforces', 'user.info', url1, self.__username, page1)
    page2 = _request_get(url2, 'codeforces', 'user.rating')
    _log_diagnostic('codeforces', 'user.rating', url2, self.__username, page2)
    try:
        r_data = page1.json()
        _log_diagnostic('codeforces', 'user.info_parser', url1,
                        self.__username, page1,
                        json_shape_valid=isinstance(r_data, dict),
                        result_present=bool(r_data.get('result'))
                        if isinstance(r_data, dict) else False)
    except Exception as error:
        _log_diagnostic('codeforces', 'user.info_parser', url1,
                        self.__username, page1,
                        failure_category='UPSTREAM_RESPONSE_INVALID',
                        exception_type=type(error).__name__)
        raise
    data  = dict()
    data['status'] = 'OK'
    data.update(r_data['result'][0])
    try:
        rating_data = page2.json()
    except Exception as error:
        raise StructureError(
            'Codeforces user.rating response is not valid JSON') from error
    if not isinstance(rating_data, dict) or rating_data.get('status') != 'OK':
        raise StructureError('Codeforces user.rating response status invalid')
    if not isinstance(rating_data.get('result'), list):
        raise StructureError('Codeforces user.rating result is not a list')

    contests = []
    for contest in rating_data['result']:
        if not isinstance(contest, dict):
            raise StructureError('Codeforces user.rating contest is not an object')
        required_fields = {'contestName', 'rank', 'oldRating', 'newRating'}
        if not required_fields.issubset(contest):
            raise StructureError('Codeforces user.rating contest fields missing')
        contests.append({
            "contest": contest['contestName'],
            "rank": str(contest['rank']),
            "solved": "NA",
            "ratingChange": f"{contest['newRating'] - contest['oldRating']:+d}",
            "newRating": str(contest['newRating'])
        })
    data['contests']=contests
    return data

  def __leetcode(self):
    def __parse_response(response):
      total_submissions_count = 0
      total_easy_submissions_count = 0
      total_medium_submissions_count = 0
      total_hard_submissions_count = 0

      ac_submissions_count = 0
      ac_easy_submissions_count = 0
      ac_medium_submissions_count = 0
      ac_hard_submissions_count = 0

      total_easy_questions = 0
      total_medium_questions = 0
      total_hard_questions = 0

      total_problems_solved = 0
      easy_questions_solved = 0
      medium_questions_solved = 0
      hard_questions_solved = 0

      acceptance_rate = 0
      easy_acceptance_rate = 0
      medium_acceptance_rate = 0
      hard_acceptance_rate = 0

      total_problems_submitted = 0
      easy_problems_submitted = 0
      medium_problems_submitted = 0
      hard_problems_submitted = 0

      matched_user = get_safe_nested_key(['data', 'matchedUser'], response)
      if matched_user is None:
          raise StructureError('LeetCode matched user missing')
      ranking = get_safe_nested_key(['data', 'matchedUser', 'profile', 'ranking'], response)
      if ranking > 100000:
          ranking = '~100000'

      reputation = get_safe_nested_key(['data', 'matchedUser', 'profile', 'reputation'], response)

      total_questions_stats = get_safe_nested_key(['data', 'allQuestionsCount'], response)
      for item in total_questions_stats:
          if item['difficulty'] == "Easy":
              total_easy_questions = item['count']
          if item['difficulty'] == "Medium":
              total_medium_questions = item['count']
          if item['difficulty'] == "Hard":
              total_hard_questions = item['count']

      ac_submissions = get_safe_nested_key(['data', 'matchedUser', 'submitStats', 'acSubmissionNum'], response)
      for submission in ac_submissions:
          if submission['difficulty'] == "All":
              total_problems_solved = submission['count']
              ac_submissions_count = submission['submissions']
          if submission['difficulty'] == "Easy":
              easy_questions_solved = submission['count']
              ac_easy_submissions_count = submission['submissions']
          if submission['difficulty'] == "Medium":
              medium_questions_solved = submission['count']
              ac_medium_submissions_count = submission['submissions']
          if submission['difficulty'] == "Hard":
              hard_questions_solved = submission['count']
              ac_hard_submissions_count = submission['submissions']

      total_submissions = get_safe_nested_key(['data', 'matchedUser', 'submitStats', 'totalSubmissionNum'],
                                              response)
      for submission in total_submissions:
          if submission['difficulty'] == "All":
              total_problems_submitted = submission['count']
              total_submissions_count = submission['submissions']
          if submission['difficulty'] == "Easy":
              easy_problems_submitted = submission['count']
              total_easy_submissions_count = submission['submissions']
          if submission['difficulty'] == "Medium":
              medium_problems_submitted = submission['count']
              total_medium_submissions_count = submission['submissions']
          if submission['difficulty'] == "Hard":
              hard_problems_submitted = submission['count']
              total_hard_submissions_count = submission['submissions']

      if total_submissions_count > 0:
          acceptance_rate = round(ac_submissions_count * 100 / total_submissions_count, 2)
      if total_easy_submissions_count > 0:
          easy_acceptance_rate = round(ac_easy_submissions_count * 100 / total_easy_submissions_count, 2)
      if total_medium_submissions_count > 0:
          medium_acceptance_rate = round(ac_medium_submissions_count * 100 / total_medium_submissions_count, 2)
      if total_hard_submissions_count > 0:
          hard_acceptance_rate = round(ac_hard_submissions_count * 100 / total_hard_submissions_count, 2)

      contribution_points = get_safe_nested_key(['data', 'matchedUser', 'contributions', 'points'],
                                                response)
      contribution_problems = get_safe_nested_key(['data', 'matchedUser', 'contributions', 'questionCount'],
                                                  response)
      contribution_testcases = get_safe_nested_key(['data', 'matchedUser', 'contributions', 'testcaseCount'],
                                                    response)

      return {
          'status': 'OK',
          'ranking': str(ranking),
          'total_problems_submitted': str(total_problems_submitted),
          'total_problems_solved': str(total_problems_solved),
          'acceptance_rate': f"{acceptance_rate}%",
          'easy_problems_submitted': str(easy_problems_submitted),
          'easy_questions_solved': str(easy_questions_solved),
          'easy_acceptance_rate': f"{easy_acceptance_rate}%",
          'total_easy_questions': str(total_easy_questions),
          'medium_problems_submitted': str(medium_problems_submitted),
          'medium_questions_solved': str(medium_questions_solved),
          'medium_acceptance_rate': f"{medium_acceptance_rate}%",
          'total_medium_questions': str(total_medium_questions),
          'hard_problems_submitted': str(hard_problems_submitted),
          'hard_questions_solved': str(hard_questions_solved),
          'hard_acceptance_rate': f"{hard_acceptance_rate}%",
          'total_hard_questions': str(total_hard_questions),
          'contribution_points': str(contribution_points),
          'contribution_problems': str(contribution_problems),
          'contribution_testcases': str(contribution_testcases),
          'reputation': str(reputation)
      }

    url = f'https://leetcode.com/{self.__username}'
    profile_response = _request_get(url, 'leetcode', 'profile',
                                    username_lookup=True)
    _log_diagnostic('leetcode', 'profile', url, self.__username,
                    profile_response, expected_gate='profile_status_200')
    payload = {
        "operationName": "getUserProfile",
        "variables": {
            "username": self.__username
        },
        "query": "query getUserProfile($username: String!) {  allQuestionsCount {    difficulty    count  }  matchedUser(username: $username) {    contributions {    points      questionCount      testcaseCount    }    profile {    reputation      ranking    }    submitStats {      acSubmissionNum {        difficulty        count        submissions      }      totalSubmissionNum {        difficulty        count        submissions      }    }  }}"
    }
    graphql_url = 'https://leetcode.com/graphql'
    res = _request_post(
        graphql_url, 'leetcode', 'graphql',
        json=payload,
        headers={'referer': f'https://leetcode.com/{self.__username}/'})
    _log_diagnostic('leetcode', 'graphql', graphql_url, self.__username,
                    res, expected_gate='graphql_json')
    try:
        res = res.json()
        _log_diagnostic('leetcode', 'graphql_parser', graphql_url,
                        self.__username,
                        json_shape_valid=isinstance(res, dict),
                        matched_user_present=bool(
                            get_safe_nested_key(['data', 'matchedUser'], res)
                        ))
    except Exception as error:
        _log_diagnostic('leetcode', 'graphql_parser', graphql_url,
                        self.__username,
                        failure_category='UPSTREAM_RESPONSE_INVALID',
                        exception_type=type(error).__name__)
        raise StructureError('LeetCode GraphQL response is not valid JSON') from error
    return __parse_response(res)

  def __spoj(self):
    url = "https://www.spoj.com/users/{}/".format(self.__username)
    session = HTMLSession()
    try:
        r = session.get(url,timeout=10)
    except requests.exceptions.RequestException as error:
        raise UpstreamTransportError(
            platform='spoj', operation='profile', url=url,
            username_lookup=True, cause=error)
    _validate_upstream_response(r, 'spoj', 'profile', url, True)
    _log_diagnostic('spoj', 'profile', url, self.__username, r)
    profile_elements = r.html.find("#user-profile-left")
    _log_diagnostic('spoj', 'profile_parser', url, self.__username, r,
                    profile_container_present=bool(profile_elements))
    user_profile_left = profile_elements
    if not len(user_profile_left):
        raise StructureError('SPOJ profile container missing')
    data = dict()
    user_profile_left = user_profile_left[0]
    data['full_name'] = user_profile_left.find('h3',first=True).text
    p_data = user_profile_left.find('p')
    location = p_data[0].text
    data_stats = r.html.find('.profile-info-data-stats',first=True)
    dts = data_stats.find('dt')
    dds = data_stats.find('dd')
    for dt,dd in zip(dts,dds):
      data[dt.text] = dd.text
    page = _request_get(url, 'spoj', 'profile_details')
    _log_diagnostic('spoj', 'profile_details', url, self.__username, page)
    soup = BeautifulSoup(page.text, 'html.parser')
    top=soup.find('div', id='user-profile-left')
    img = top.find('img')['src']
    details_container = soup.find_all('p')
    points = details_container[2].text.split()[3][1:]
    rank = details_container[2].text.split()[2][1:]
    join_date = details_container[1].text.split()[1] + ' ' + details_container[1].text.split()[2]
    institute = ' '.join(details_container[3].text.split()[1:])
    try:
        points = float(points)
    except ValueError:
        raise UsernameError('User not Found')
    
    def get_solved_problems():
        table = soup.find('table', class_='table table-condensed')
        rows = table.findChildren('td')
        solved_problems = []
        for row in rows:
            if row.a.text:
                solved_problems.append(row.a.text)
        return solved_problems

    def get_todo():
        try:
            table = soup.find_all('table', class_='table')[1]
        except:
            return None
        rows = table.findChildren('td')
        todo_problems = []
        for row in rows:
            if row.a.text:
                todo_problems.append(row.a.text)
        return todo_problems

    details = {'status': 'OK', 'fullname': data['full_name'], 'username': self.__username, 'location': location, 'img_scr':img, 'points': float(points), 'rank': int(rank), 'solved': get_solved_problems(),  'todo': get_todo(), 'join_date': join_date, 'institute': institute, 'problems_solved': data['Problems solved'], 
    'solution_submitted': data['Solutions submitted']
    }
    return details

  def __atcoder(self):
    url = "https://atcoder.jp/users/{}".format(self.__username)
    session = HTMLSession()
    try:
        r = session.get(url, timeout=10)
    except requests.exceptions.RequestException as error:
        raise UpstreamTransportError(
            platform='atcoder', operation='profile_html_session', url=url,
            username_lookup=True, cause=error)
    _validate_upstream_response(r, 'atcoder', 'profile_html_session', url, True)
    _log_diagnostic('atcoder', 'profile_html_session', url,
                    self.__username, r)
    page = _request_get(url, 'atcoder', 'profile_requests', True)
    _log_diagnostic('atcoder', 'profile_requests', url, self.__username, page)
    data_tables = r.html.find('.dl-table')
    _log_diagnostic('atcoder', 'profile_parser', url, self.__username, r,
                    dl_table_count=len(data_tables),
                    expected_gate='at_least_one_dl_table')
    if not len(data_tables):
        raise StructureError('AtCoder profile table missing')
    soup = BeautifulSoup(page.text, "html.parser")
    tables = soup.find_all("table", class_="dl-table")
    data = dict()
    known_profile_labels = {
        'Country/Region', 'Birth Year', 'Affiliation', 'Rating',
        'Highest Rating', 'Rank', 'Level'
    }
    for table in tables:
      for row in table.find_all('tr'):
        header = row.find('th')
        value_cell = row.find('td')
        if header is None or value_cell is None:
          continue
        label = header.get_text(strip=True)
        spans = value_cell.find_all('span')
        value = (spans[-1].get_text(strip=True)
                 if label == 'Level' and spans
                 else value_cell.get_text(' ', strip=True))
        data[label] = value
    if not known_profile_labels.intersection(data):
      raise StructureError('AtCoder profile labels missing')
    _log_diagnostic('atcoder', 'rating_parser', url, self.__username, page,
                    dl_table_count=len(tables),
                    rating_fields_present=bool(
                        {'Rating', 'Highest Rating', 'Rank', 'Level'}
                        .intersection(data)))

    def numeric_or_na(value):
      match = re.search(r'\d+', value or '')
      return int(match.group()) if match else 'NA'

    current_rating = numeric_or_na(data.get('Rating'))
    highest_rating = numeric_or_na(data.get('Highest Rating'))
    rank = numeric_or_na(data.get('Rank'))
    level = data.get('Level', 'NA')
    details = {
        "status": "OK",
        "platform": "Atcoder",
        "username": self.__username,
        "rating": current_rating,
        "highest": highest_rating,
        "rank": rank,
        "level": level,
        'other':data
    }
    return details

  def get_details(self, platform):
    if platform == 'codechef':
      return self.__codechef()
    
    if platform == 'codeforces':
      return self.__codeforces()
    
    if platform == 'leetcode':
      return self.__leetcode()
    
    if platform == 'spoj':
      return self.__spoj()

    if platform == 'atcoder':
      return self.__atcoder()

    raise PlatformError('Platform not Found')