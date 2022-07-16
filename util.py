import json
import re
import requests
from requests_html import HTMLSession
from bs4 import BeautifulSoup

class UsernameError(Exception):
  pass

class PlatformError(Exception):
  pass

class BrokenChangesError(Exception):
  pass

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
    page = requests.get(url)
    soup = BeautifulSoup(page.text, 'html.parser')
    try:
        rating = soup.find('div', class_='rating-number').text
    except AttributeError:
        raise UsernameError('User not Found')
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
    url2 = 'https://codeforces.com/contests/with/{}'.format(self.__username)
    page1 = requests.get(url1)
    page2 = requests.get(url2)
    if page1.status_code != 200 and page2.status_code != 200:
        raise UsernameError('User not found')
    r_data = page1.json()
    data  = dict()
    data['status'] = 'OK'
    data.update(r_data['result'][0])
    soup = BeautifulSoup(page2.text, 'html.parser')
    table = soup.find('table', attrs={'class': 'user-contests-table'})
    table_body = table.find('tbody')

    rows = table_body.find_all('tr')
    contests = []
    for row in rows:
        cols = row.find_all('td')
        cols = [ele.text.strip() for ele in cols]
        contests.append({
            "contest": cols[1],
            "rank": cols[3],
            "solved": cols[4],
            "ratingChange": cols[5],
            "newRating": cols[6]
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
    if requests.get(url).status_code != 200:
        raise UsernameError('User not Found')
    payload = {
        "operationName": "getUserProfile",
        "variables": {
            "username": self.__username
        },
        "query": "query getUserProfile($username: String!) {  allQuestionsCount {    difficulty    count  }  matchedUser(username: $username) {    contributions {    points      questionCount      testcaseCount    }    profile {    reputation      ranking    }    submitStats {      acSubmissionNum {        difficulty        count        submissions      }      totalSubmissionNum {        difficulty        count        submissions      }    }  }}"
    }
    res = requests.post(url='https://leetcode.com/graphql',
                        json=payload,
                        headers={'referer': f'https://leetcode.com/{self.__username}/'})
    res.raise_for_status()
    res = res.json()
    return __parse_response(res)

  def __spoj(self):
    url = "https://www.spoj.com/users/{}/".format(self.__username)
    session = HTMLSession()
    r = session.get(url,timeout=10)
    if r.status_code !=200:
        raise UsernameError("User not found")
    user_profile_left = r.html.find("#user-profile-left")
    if not len(user_profile_left):
        raise UsernameError
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
    page = requests.get(url)
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
    r = session.get(url, timeout=10)
    page = requests.get(url)
    if page.status_code != 200 and r.status_code != 200:
        raise UsernameError("User not Found")
    data_tables = r.html.find('.dl-table')
    if not len(data_tables):
        raise UsernameError('User not found')
    data = dict()
    for table in data_tables:
      data_rows = table.find('tr')
      for row in data_rows:
        attr = row.find('th',first=True).text
        val = row.find('td',first=True).text
        data[attr]=val
        if attr == 'Highest Rating':
          val = val.split()[0]
          data[attr]=val
    soup = BeautifulSoup(page.text, "html.parser")
    tables = soup.find_all("table", class_="dl-table")
    if len(tables) < 2:
      details = {
        "status": "OK",
        "username": self.__username,
        "platform": "Atcoder",
        "rating": "NA",
        "highest": "NA",
        "rank": "NA",
        "level": "NA",
        'other':data
      }
      return details
    rows = tables[1].find_all("td")
    try:
        rank = int(rows[0].text[:-2])
        current_rating = int(rows[1].text)
        spans = rows[2].find_all("span")
        highest_rating = int(spans[0].text)
        level = spans[2].text
    except Exception as E:
        raise BrokenChangesError(E)
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