import traceback; import sys; 
try:
    import main
    main.main()
except Exception as e:
    print('ERROR:', e)
    traceback.print_exc()
    sys.exit(1)
