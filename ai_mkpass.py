#!/usr/bin/env python3


try:
    import sys
    import linecache
    import argparse
    from random import SystemRandom
    import string
    from re import search
    from pathlib import Path
    from passlib.hash import sha512_crypt  # from passlib
    import time
except (ImportError, ModuleNotFoundError) as err:
    print(err, file=sys.stderr)
    sys.exit(1)


#init random
RAND = SystemRandom()


def file_len(fname):
    i = -1
    try:
        with open(fname) as f:
            for i, _ in enumerate(f):
                pass
    except IOError:
        sys.exit(str("File Error: Cannot find '" + fname + "'"))
    return i + 1


def mk_dict_pwd(my_dict=None):
    # Allow user to overrride dictionary, but default to using a local dict
    if my_dict is None:
        mypath = Path(__file__).resolve().parents[0]
        my_dict = str(mypath) + "/randudict.dict"

    # concatenate 4 words @ random from dictonary w/ spaces
    LineCount = file_len(my_dict)
    if LineCount > 0:
        pwd = ''
        for _ in range(4):
            offset = RAND.randint(1, LineCount)
            pwd += str(linecache.getline(my_dict, offset)).strip() + ' '
        return pwd.strip().capitalize()
    else:
        sys.exit(str('Error: ' + my_dict + ' appears to be empty.'))


def mk_hash(passwd):
    maxrounds = 67539
    passhash = sha512_crypt.encrypt(passwd, rounds=RAND.randint(1024, maxrounds))
    return passhash


def get_pwd(pwd_length, charset):
    pwd = ''
    for _ in range(pwd_length):
        pwd = pwd + charset[RAND.randrange(len(charset))]
    return pwd


def ops_pwd(length, charset):
    ops_pass = get_pwd(length, charset)
    while not (search(r'([!@#\$%\^&\*\(\)\{\}\[\];:/])', ops_pass) and search(r'[0-9]', ops_pass) and search('[A-Z]', ops_pass)):
        ops_pass = get_pwd(length, charset)
    return ops_pass


def user_pwd(length, charset):
    user_pass = ops_pwd(length, charset)
    while not search(r'[a-z]{5,6}', user_pass):
        user_pass = ops_pwd(length, charset)
    return user_pass


def temp_pwd():
    join_str = str(time.time())[-3:] + '-'
    user_pass = join_str.join(mk_dict_pwd().split()[:2])
    return user_pass


def ai_mkpass(pwd_type='strong', pwd_length=14, char_set=None, hash_pwd=None):
    if char_set is None:
        char_set = string.ascii_letters + string.digits + '!@#$%^&*(){}[];:/'
    my_pass = None
    if pwd_type == 'dict':
        my_pass = mk_dict_pwd()
    elif pwd_type == 'nice':
        my_pass = user_pwd(pwd_length, char_set)
    elif pwd_type == 'bios':
        my_pass = get_pwd(pwd_length, char_set)
    elif pwd_type == 'temp':
        my_pass = temp_pwd()
    elif pwd_type == 'hash':
        if hash_pwd is not None:
            my_pass = mk_hash(hash_pwd)
    else:
        # Default to strongpass
        my_pass = ops_pwd(pwd_length, char_set)
    return my_pass


def handle_arguments():
    #  Set Default params
    pwd_length = 14
    parser = argparse.ArgumentParser(description='Universal password creation tool. Defaults to creating a {len} character strong password.'.format(len=pwd_length))
    parser.add_argument('-d', '--dict', action='store_true', help="Create a password based on dictionary words")
    parser.add_argument('-s', '--strong', action='store_true', help="Create a strong random password")
    parser.add_argument('-n', '--nice', action='store_true', help="Create a strong random password")
    parser.add_argument('-b', '--bios', action='store_true', help="Create a BIOS compatible password (no special chars)")
    parser.add_argument('-t', '--temp', action='store_true', help="Create a temporary user password")

    parser.add_argument('-l', '--length', type=int, default=pwd_length, help="Length of password (use with --strong or --nice). Default is {len}".format(len=pwd_length))
    parser.add_argument('--hash', action='store_true', help="Generates a sha512 hash of a password. use with -p to specify password to hash")
    parser.add_argument('-p', '--password', help="Used with --hash for password input")
    args = parser.parse_args()
    if args.hash:
        if not args.password:
            parser.error("--hash requires a password paramater via -p or --password")
    return args


def main():

    # Set Default params
    bios_charset = string.ascii_letters + string.digits

    args = handle_arguments()

    if (args.dict):
        print(ai_mkpass('dict', args.length))
    elif (args.nice):
        print(ai_mkpass('nice', args.length))
    elif (args.bios):
        print(ai_mkpass('bios', args.length, bios_charset))
    elif (args.temp):
        print(ai_mkpass('temp'))
    elif (args.hash):
        print(ai_mkpass('hash', args.length, hash_pwd=args.password))
    else:
        print(ai_mkpass('strong', args.length))


if __name__ == "__main__":
    try:    
        main()
    except KeyboardInterrupt:
        print("Caught Ctrl-C")
        exit(0)
