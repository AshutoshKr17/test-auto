import requests
import time
import re
import paramiko
import pymysql
import subprocess
import random

JENKINS_URL = 'https://jenkins.cloudways.services/'  # Replace with actual Jenkins URL
JOB_NAME = 'test'  # Job is inside 'environment' folder
USERNAME = 'test'
API_TOKEN = 'Test'

# SSH Configuration for MySQL connection
SSH_HOST = 'test'
SSH_PORT = test
SSH_USERNAME = 'test'
SSH_KEY_PATH = 'test'

def read_user_params():
    """Read parameters from userParams.txt file"""
    params = {}
    try:
        with open('userParams.txt', 'r') as f:
            lines = [line.strip() for line in f.readlines()]
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines and notes
            if not line or line.startswith('Note:'):
                i += 1
                continue
            
            # Check if this line looks like a parameter name (all caps with underscores)
            if re.match(r'^[A-Z_]+$', line):
                param_name = line
                i += 1
                
                # Skip description lines and find the actual value
                while i < len(lines):
                    current_line = lines[i].strip()
                    
                    # If we hit another parameter name, break
                    if re.match(r'^[A-Z_]+$', current_line):
                        break
                    
                    # Skip notes and empty lines
                    if not current_line or current_line.startswith('Note:'):
                        i += 1
                        continue
                    
                    # If it's not a description (doesn't contain "name" or "Branch"), it's likely a value
                    if not any(word in current_line.lower() for word in ['name', 'branch', 'endpoint', 'service']):
                        param_value = current_line
                        if param_value:  # Only add non-empty values
                            params[param_name] = param_value
                        break
                    
                    i += 1
                    
            else:
                i += 1
        
        # Validate ENV_NAME format if present
        if 'ENV_NAME' in params:
            env_name = params['ENV_NAME']
            if not re.match(r'^[a-z]{1,3}$', env_name):
                print(f"Warning: ENV_NAME '{env_name}' should be max 3 lowercase letters")
        
        return params
    
    except FileNotFoundError:
        print("Error: userParams.txt file not found")
        return {}
    except Exception as e:
        print(f"Error reading userParams.txt: {e}")
        return {}

def test_jenkins_connection():
    """Test if Jenkins server is reachable"""
    try:
        print("Testing Jenkins connection...")
        url = f"{JENKINS_URL}/api/json"
        response = requests.get(url, auth=(USERNAME, API_TOKEN), timeout=10)
        
        if response.status_code == 200:
            print("✓ Jenkins connection successful")
            return True
        else:
            print(f"✗ Jenkins connection failed: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        print("✗ Jenkins connection timed out - Are you connected to VPN?")
        return False
    except requests.exceptions.ConnectionError:
        print("✗ Cannot reach Jenkins server - Are you connected to VPN?")
        return False
    except Exception as e:
        print(f"✗ Jenkins connection error: {e}")
        return False

def check_job_exists():
    """Check if the Jenkins job exists and get its details"""
    try:
        print(f"Checking if job '{JOB_NAME}' exists...")
        url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/api/json"
        response = requests.get(url, auth=(USERNAME, API_TOKEN), timeout=10)
        
        if response.status_code == 200:
            job_info = response.json()
            print(f"✓ Job '{JOB_NAME}' found")
            return True
        elif response.status_code == 404:
            print(f"✗ Job '{JOB_NAME}' not found (404)")
            return False
        else:
            print(f"✗ Error checking job: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ Error checking job: {e}")
        return False

def trigger_job(params):
    """Trigger Jenkins job with parameters and return build number"""
    try:
        # For parameterized builds, use /buildWithParameters
        if params:
            build_url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/buildWithParameters"
            print(f"Triggering parameterized build: {build_url}")
        else:
            build_url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/build"
            print(f"Triggering simple build: {build_url}")
        
        # Jenkins expects parameters in a specific format for POST requests
        response = requests.post(build_url, auth=(USERNAME, API_TOKEN), data=params, timeout=30)
        
        if response.status_code == 201:
            print("✓ Job triggered successfully.")
            
            # Get the queue item location from the response header
            queue_location = response.headers.get('Location')
            if queue_location:
                print(f"Build queued at: {queue_location}")
                # Extract build number from queue
                build_number = get_build_number_from_queue(queue_location)
                return build_number
            else:
                print("⚠️  No queue location in response, falling back to last build method")
                return get_last_build_number()
                
        elif response.status_code == 404:
            print("✗ Job trigger failed: 404 Not Found")
            return None
        else:
            print(f"✗ Failed to trigger job: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Job trigger error: {e}")
        return None

def get_build_number_from_queue(queue_location):
    """Get build number from Jenkins queue location"""
    try:
        print("Waiting for build to start from queue...")
        max_attempts = 30  # Wait up to 30 seconds for build to start
        
        for attempt in range(max_attempts):
            try:
                # Get queue item details
                queue_response = requests.get(f"{queue_location}api/json", auth=(USERNAME, API_TOKEN), timeout=10)
                
                if queue_response.status_code == 200:
                    queue_data = queue_response.json()
                    
                    # Check if build has started (executable field will contain build info)
                    executable = queue_data.get('executable')
                    if executable:
                        build_number = executable.get('number')
                        if build_number:
                            print(f"✓ Build started with number: #{build_number}")
                            return build_number
                    
                    # If still in queue, wait a bit
                    print(f"  Attempt {attempt + 1}/{max_attempts}: Build still in queue...")
                    time.sleep(1)
                else:
                    print(f"  Warning: Could not check queue status: {queue_response.status_code}")
                    time.sleep(1)
                    
            except Exception as e:
                print(f"  Error checking queue: {e}")
                time.sleep(1)
        
        print("⚠️  Timeout waiting for build to start from queue, falling back to last build method")
        return get_last_build_number()
        
    except Exception as e:
        print(f"✗ Error getting build number from queue: {e}")
        return get_last_build_number()

def get_last_build_number():
    url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/api/json"
    response = requests.get(url, auth=(USERNAME, API_TOKEN))
    return response.json()['lastBuild']['number']

def wait_for_job_completion(build_number):
    url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/{build_number}/api/json"
    while True:
        response = requests.get(url, auth=(USERNAME, API_TOKEN)).json()
        if not response['building']:
            print("Job completed.")
            return
        print("Waiting for job to complete...")
        time.sleep(10)

def fetch_console_output(build_number):
    url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/{build_number}/consoleText"
    response = requests.get(url, auth=(USERNAME, API_TOKEN))
    return response.text

def extract_info(console_output):
    # Use regex to extract the values
    patterns = {
        "elk": r"ELK EndPoint:\s*(\S+)",
        "scannerapi": r"Scannerapi EndPoint:\s*(\S+)",
        "alb": r"ALB EndPoint:\s*(\S+)",
        "cnc": r"cnc EndPoint:\s*(\S+)",
        "api": r"api-endpoint:\s*(\S+)",
        "private_ips": r"Instance PrivateIP:\s*((?:\d{1,3}\.){3}\d{1,3}(?:\n\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})?)",
        "mysql_user": r"MySQL User:\s*(\S+)",
        "mysql_pass": r"MySQL Pass:\s*(\S+)",
        "pgsql_host": r"pgSQL private HOST:\s*(\S+)",
        "pgsql_user": r"pgSQL User:\s*(\S+)",
        "pgsql_pass": r"pgSQL Pass:\s*(\S+)"
    }

    extracted = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, console_output)
        if match:
            extracted[key] = match.group(1).strip()
    
    # Extract MySQL IPs separately (there can be multiple)
    mysql_ips = []
    lines = console_output.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        # Look for MySQL private HOST followed by IP addresses
        if 'MySQL private HOST:' in line:
            # Check next few lines for IP addresses
            for j in range(i+1, min(i+4, len(lines))):
                next_line = lines[j].strip()
                # Check if it's an IP address
                ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
                ips = re.findall(ip_pattern, next_line)
                mysql_ips.extend(ips)
    
    # Remove duplicates and add to extracted info
    mysql_ips = list(set(mysql_ips))
    if mysql_ips:
        extracted['mysql_ips'] = mysql_ips
    
    return extracted

def test_mysql_connection(mysql_host, mysql_user, mysql_pass):
    """Test MySQL connection to a specific host"""
    local_port = random.randint(3308, 3320)
    tunnel_process = None
    
    try:
        print(f"Testing MySQL connection to {mysql_host}...")
        
        # Kill any existing tunnels
        subprocess.run(['pkill', '-f', f'{local_port}:{mysql_host}:3306'], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        
        # Create SSH tunnel
        tunnel_cmd = [
            'ssh', '-i', SSH_KEY_PATH,
            '-L', f'{local_port}:{mysql_host}:3306',
            '-N', f'{SSH_USERNAME}@{SSH_HOST}',
            '-p', str(SSH_PORT),
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'ConnectTimeout=10'
        ]
        
        print(f"  Creating SSH tunnel: localhost:{local_port} -> {mysql_host}:3306")
        
        tunnel_process = subprocess.Popen(
            tunnel_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        time.sleep(5)  # Wait for tunnel
        
        # Check if tunnel is running
        if tunnel_process.poll() is not None:
            stderr = tunnel_process.stderr.read().decode('utf-8')
            print(f"  ✗ SSH tunnel failed: {stderr}")
            return None, None
        
        print(f"  SSH tunnel established on port {local_port}")
        
        # Test MySQL connection
        connection = pymysql.connect(
            host='127.0.0.1',
            port=local_port,
            user=mysql_user,
            password=mysql_pass,
            connect_timeout=10,
            charset='utf8mb4'
        )
        
        print(f"✓ MySQL connection to {mysql_host} successful")
        
        # Check for cloudways_new database
        cursor = connection.cursor()
        cursor.execute("SHOW DATABASES")
        databases = [db[0] for db in cursor.fetchall()]
        
        print(f"  Databases: {databases}")
        
        # Look for cloudways_new database
        if 'cloudways_new' in databases:
            print(f"  ✓ Found 'cloudways_new' database on {mysql_host}")
            
            # Connect to the cloudways_new database and show tables
            cursor.execute("USE cloudways_new")
            cursor.execute("SHOW TABLES")
            tables = [table[0] for table in cursor.fetchall()]
            print(f"  Tables in cloudways_new database: {tables}")
            
            connection.close()
            tunnel_process.terminate()
            return mysql_host, 'cloudways_new'
        
        print(f"  ✗ 'cloudways_new' database not found on {mysql_host}")
        connection.close()
        tunnel_process.terminate()
        return None, None
        
    except Exception as e:
        print(f"✗ MySQL connection to {mysql_host} failed: {e}")
        if tunnel_process:
            tunnel_process.terminate()
        return None, None

def connect_and_work_with_database(mysql_host, database, mysql_user, mysql_pass):
    """Connect to MySQL database and show basic information"""
    local_port = random.randint(3308, 3320)
    tunnel_process = None
    
    try:
        print(f"\nConnecting to MySQL database '{database}' on {mysql_host}...")
        
        # Kill any existing tunnels
        subprocess.run(['pkill', '-f', f'{local_port}:{mysql_host}:3306'], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        
        # Create SSH tunnel
        tunnel_cmd = [
            'ssh', '-i', SSH_KEY_PATH,
            '-L', f'{local_port}:{mysql_host}:3306',
            '-N', f'{SSH_USERNAME}@{SSH_HOST}',
            '-p', str(SSH_PORT),
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'ConnectTimeout=10'
        ]
        
        tunnel_process = subprocess.Popen(
            tunnel_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        time.sleep(5)  # Wait for tunnel
        
        # Connect to MySQL
        connection = pymysql.connect(
            host='127.0.0.1',
            port=local_port,
            user=mysql_user,
            password=mysql_pass,
            database=database,
            connect_timeout=10,
            charset='utf8mb4'
        )
        
        print(f"✓ Connected to MySQL database '{database}' on {mysql_host}")
        
        # Show database info
        cursor = connection.cursor()
        cursor.execute("SHOW TABLES")
        tables = [table[0] for table in cursor.fetchall()]
        print(f"\nTables in '{database}' database:")
        for table in tables:
            print(f"  - {table}")
        
        # Check if users table exists
        if 'users' not in tables:
            print("✗ 'users' table not found in database")
            connection.close()
            tunnel_process.terminate()
            return False
        
        print(f"\n✓ Found 'users' table")
        
        # Show users table structure
        cursor.execute("DESCRIBE users")
        columns = cursor.fetchall()
        print(f"\nUsers table structure:")
        for col in columns:
            print(f"  {col[0]} ({col[1]})")
        
        print(f"\n✓ Database connection successful! Ready for operations.")
        
        connection.close()
        tunnel_process.terminate()
        print(f"\n✓ Database connection completed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Error working with database: {e}")
        if tunnel_process:
            tunnel_process.terminate()
        return False

def connect_to_mysql_database(mysql_info):
    """Connect to MySQL database using extracted information"""
    try:
        print("\n" + "="*60)
        print("CONNECTING TO MYSQL DATABASE")
        print("="*60)
        
        mysql_ips = mysql_info.get('mysql_ips', [])
        mysql_user = mysql_info.get('mysql_user')
        mysql_pass = mysql_info.get('mysql_pass')
        
        if not mysql_ips or not mysql_user or not mysql_pass:
            print("✗ Missing MySQL connection details")
            return False
        
        print(f"MySQL IPs to test: {mysql_ips}")
        print(f"MySQL User: {mysql_user}")
        
        # Test each MySQL IP to find the one with cloudways_new database
        for mysql_ip in mysql_ips:
            host, database = test_mysql_connection(mysql_ip, mysql_user, mysql_pass)
            if host and database:
                print(f"\n✓ Successfully found MySQL server with 'cloudways_new' database!")
                print(f"  Host: {host}")
                print(f"  Database: {database}")
                
                # Show database connection details
                print(f"\nConnecting to database to verify connection...")
                connect_and_work_with_database(host, database, mysql_user, mysql_pass)
                
                return True
        
        print("✗ Could not find MySQL server with 'cloudways_new' database")
        return False
        
    except Exception as e:
        print(f"✗ Error connecting to MySQL database: {e}")
        return False

def check_existing_build_by_env_name(env_name):
    """Check if a build exists (successful or building) for the given ENV_NAME"""
    try:
        print(f"Checking for existing builds with ENV_NAME='{env_name}'...")
        
        # Get job information to find recent builds
        url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/api/json"
        response = requests.get(url, auth=(USERNAME, API_TOKEN), timeout=10)
        
        if response.status_code != 200:
            print(f"✗ Failed to get job information: {response.status_code}")
            return None, None, None
        
        job_info = response.json()
        builds = job_info.get('builds', [])
        
        if not builds:
            print("✗ No builds found for this job")
            return None, None, None
        
        print(f"Found {len(builds)} builds. Checking recent builds for ENV_NAME='{env_name}'...")
        
        # Check the last 10 builds to find one with matching ENV_NAME
        for build in builds[:10]:  # Check last 10 builds
            build_number = build['number']
            build_url = build['url']
            
            try:
                # Get build details
                build_detail_url = f"{build_url}api/json"
                build_response = requests.get(build_detail_url, auth=(USERNAME, API_TOKEN), timeout=10)
                
                if build_response.status_code == 200:
                    build_detail = build_response.json()
                    result = build_detail.get('result')
                    is_building = build_detail.get('building', False)
                    
                    # Get build parameters
                    actions = build_detail.get('actions', [])
                    
                    for action in actions:
                        if action.get('_class') == 'hudson.model.ParametersAction':
                            parameters = action.get('parameters', [])
                            
                            for param in parameters:
                                if param.get('name') == 'ENV_NAME' and param.get('value') == env_name:
                                    if is_building or result is None:
                                        print(f"✓ Found existing BUILDING build #{build_number} with ENV_NAME='{env_name}'")
                                        return build_number, True, 'BUILDING'
                                    elif result == 'SUCCESS':
                                        print(f"✓ Found existing SUCCESSFUL build #{build_number} with ENV_NAME='{env_name}'")
                                        return build_number, True, 'SUCCESS'
                                    else:
                                        print(f"  Build #{build_number}: {result} with ENV_NAME='{env_name}' (will create new)")
                    
                    # If we reach here, this build doesn't have our ENV_NAME
                    if result == 'SUCCESS':
                        print(f"  Build #{build_number}: SUCCESS but different ENV_NAME")
                    else:
                        print(f"  Build #{build_number}: {result or 'BUILDING'} with different ENV_NAME")
                        
            except Exception as e:
                print(f"  Error checking build #{build_number}: {e}")
                continue
        
        print(f"✗ No existing build found with ENV_NAME='{env_name}'")
        return None, False, None
        
    except Exception as e:
        print(f"✗ Error checking existing builds: {e}")
        return None, False, None



def fetch_console_output_for_build(build_number):
    """Fetch console output for a specific build number"""
    try:
        url = f"{JENKINS_URL}/job/Environments/job/{JOB_NAME}/{build_number}/consoleText"
        response = requests.get(url, auth=(USERNAME, API_TOKEN))
        if response.status_code == 200:
            return response.text
        else:
            print(f"✗ Failed to fetch console output for build #{build_number}")
            return None
    except Exception as e:
        print(f"✗ Error fetching console output: {e}")
        return None

def main():
    print("=== AUTOMATED MYSQL CONNECTION ===")
    
    # Read parameters first to get ENV_NAME
    print("Reading parameters from userParams.txt...")
    params = read_user_params()
    if not params:
        print("No parameters found or error reading file. Exiting.")
        return
    
    print(f"\nFound {len(params)} parameters:")
    for key, value in params.items():
        print(f"  {key}: {value}")
    
    env_name = params.get('ENV_NAME')
    if not env_name:
        print("✗ ENV_NAME not found in parameters. Cannot proceed.")
        return
    
    print(f"\nLooking for existing builds with ENV_NAME='{env_name}'...")
    
    # Check if we should use an existing build based on ENV_NAME
    existing_build_number, build_exists, build_status = check_existing_build_by_env_name(env_name)
    
    if build_exists and existing_build_number:
        if build_status == 'BUILDING':
            print(f"Found existing BUILDING build #{existing_build_number} with ENV_NAME='{env_name}'")
            print(f"Waiting for existing build #{existing_build_number} to complete instead of creating new build...")
            build_number = existing_build_number
            wait_for_job_completion(build_number)
            output = fetch_console_output(build_number)
        elif build_status == 'SUCCESS':
            print(f"Using existing SUCCESSFUL build #{existing_build_number} with ENV_NAME='{env_name}'")
            output = fetch_console_output_for_build(existing_build_number)
            
            if not output:
                print("Failed to fetch console output from existing build")
                return
    else:
        print(f"No existing build found with ENV_NAME='{env_name}'. Creating new build...")
        
        # Test Jenkins connection
        if not test_jenkins_connection():
            print("\n❌ Cannot connect to Jenkins server.")
            return
        
        # Check if job exists
        if not check_job_exists():
            print(f"\n❌ Job '{JOB_NAME}' not found.")
            return
        
        # Trigger Jenkins job
        print(f"\nTriggering Jenkins job '{JOB_NAME}' with ENV_NAME='{env_name}'...")
        build_number = trigger_job(params)
        
        if not build_number:
            print("✗ Failed to trigger job or get build number. Exiting.")
            return

        print(f"✓ Build #{build_number} triggered successfully")
        wait_for_job_completion(build_number)
        output = fetch_console_output(build_number)

    # Extract MySQL information from console output
    info = extract_info(output)

    print("\nExtracted Info:")
    for key, value in info.items():
        print(f"{key}: {value}")
    
    # Automatically connect to MySQL database
    mysql_info = {k: v for k, v in info.items() if k.startswith('mysql')}
    if mysql_info and len(mysql_info) >= 3:
        connect_to_mysql_database(mysql_info)
    else:
        print(f"\n⚠️  MySQL connection details incomplete.")

if __name__ == "__main__":
    main()
