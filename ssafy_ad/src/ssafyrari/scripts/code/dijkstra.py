#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import rospkg
import sys
import os
import copy
import numpy as np
import json
from pyproj import Proj
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

from math import cos,sin,sqrt,pow,atan2,pi
from geometry_msgs.msg import Point32,PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry,Path
from ssafy_3.msg import global_data

current_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current_path)
cred = credentials.Certificate({current_path}.pop()+'/firebase_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client()

import threading
callback_done = threading.Event()

from lib.mgeo.class_defs import *

# mgeo_dijkstra_path_1 은 Mgeo 데이터를 이용하여 시작 Node 와 목적지 Node 를 지정하여 Dijkstra 알고리즘을 적용하는 예제 입니다.
# 사용자가 직접 지정한 시작 Node 와 목적지 Node 사이 최단 경로 계산하여 global Path(전역경로) 를 생성 합니다.
# 시작 Node 와 목적지 Node 는 Rviz 의 goal pose / initial pose 두 기능을 이용하여 정의합니다.

# 노드 실행 순서 
# 0. 필수 학습 지식
# 1. Mgeo data 읽어온 후 데이터 확인
# 2. 시작 Node 와 종료 Node 정의
# 3. weight 값 계산
# 4. Dijkstra Path 초기화 로직
# 5. Dijkstra 핵심 코드
# 6. node path 생성
# 7. link path 생성
# 8. Result 판별
# 9. point path 생성
# 10. dijkstra 경로 데이터를 ROS Path 메세지 형식에 맞춰 정의
# 11. dijkstra 이용해 만든 Global Path 정보 Publish

#TODO: (0) 필수 학습 지식
'''
# dijkstra 알고리즘은 그래프 구조에서 노드 간 최단 경로를 찾는 알고리즘 입니다.
# 시작 노드부터 다른 모든 노드까지의 최단 경로를 탐색합니다.
# 다양한 서비스에서 실제로 사용 되며 인공 위성에도 사용되는 방식 입니다.
# 전체 동작 과정은 다음과 같습니다.
#
# 1. 시작 노드 지정
# 2. 시작 노드를 기준으로 다른 노드와의 비용을 저장(경로 탐색 알고리즘에서는 비용이란 경로의 크기를 의미)
# 3. 방문하지 않은 노드들 중 가장 적은 비용의 노드를 방문
# 4. 방문한 노드와 인접한 노드들을 조사해서 새로 조사된 최단 거리가 기존 발견된 최단거리 보다 작으면 정보를 갱신
#   [   새로 조사된 최단 거리 : 시작 노드에서 방문 노드 까지의 거리 비용 + 방문 노드에서 인접 노드까지의 거리 비용    ]
#   [   기존 발견된 최단 거리 : 시작 노드에서 인접 노드까지의 거리 비용                                       ]
# 5. 3 ~ 4 과정을 반복 
# 
'''
class dijkstra_path_pub :
    def __init__(self):
        rospy.init_node('dijkstra_path_pub', anonymous=True)
        rospy.Subscriber('/odom', Odometry, self.odom_callback)
        self.global_path_pub = rospy.Publisher('/global_path',Path, queue_size = 1)
        self.global_data_pub = rospy.Publisher('/global_data', global_data, queue_size = 1)
        
        

        # rospy.Subscriber('/move_base_simple/goal', PoseStamped, self.goal_callback)
        # rospy.Subscriber('/initialpose', PoseWithCovarianceStamped, self.init_callback)

        #TODO: (1) Mgeo data 읽어온 후 데이터 확인
        # load_path = os.path.normpath(os.path.join(current_path, 'lib/mgeo_data/R_KR_PG_K-City'))
        load_path = os.path.normpath(os.path.join(current_path, './lib/mgeo_data/R_KR_PR_Sangam_nobuildings'))
        mgeo_planner_map = MGeo.create_instance_from_json(load_path)

        node_set = mgeo_planner_map.node_set
        link_set = mgeo_planner_map.link_set

        self.nodes=node_set.nodes
        self.links=link_set.lines

        self.proj_UTM = Proj( proj= 'utm', zone=52 , ellps = 'WGS84' , preserve_units = False)

        self.global_planner=Dijkstra(self.nodes,self.links)

        self.is_goal_pose = False
        self.is_init_pose = False

        
        
        rate2 = rospy.Rate(1)
        while True:
            RL = Realtime_listener()
            if RL.data:
                self.init_callback(RL.data)
                self.goal_callback(RL.data)
                # print(self.is_init_pose)
            # print(self.start_node,self.end_node)
            if self.is_goal_pose == True and self.is_init_pose == True:
                break
            else:
                rospy.loginfo('Waiting goal pose data')
                rospy.loginfo('Waiting init pose data')
            rate2.sleep()
        self.check_data=RL.data

        self.global_path_msg = Path()
        self.global_path_msg.header.frame_id = '/map'
        self.HCD=[[self.egox,self.egoy],[self.init_x,self.init_y],[self.goal_x,self.goal_y]]
        # print(self.HCD)
        # rospy.loginfo(self.nodes)
        rospy.loginfo(self.node_find(self.egox,self.egoy))
        print(self.node_find(1231.2754725448322,-992.5671631838195),self.node_find(1371.3846003052313,-1100.2291121240705))
        # print(self.node_find(self.init_x,self.init_y))
        # TODO 데이터를 담아서
        # self.global_path_msg1, path1 = self.calc_dijkstra_path_node(self.node_find(self.egox,self.egoy),self.node_find(self.init_x,self.init_y))

        # self.global_path_msg1, path1 = self.calc_dijkstra_path_node(self.node_find(1006,-1684),self.node_find(-98,-646)) #출1->도1
        # self.global_path_msg1, path1 = self.calc_dijkstra_path_node(self.node_find(1231.2754725448322,-992.5671631838195),self.node_find(-73,-615)) #현->출1
        # self.global_path_msg1, path1 = self.calc_dijkstra_path_node(self.node_find(1006,-1684),self.node_find(536,-1123)) #출1->출2
        self.global_path_msg1, path1 = self.calc_dijkstra_path_node(self.node_find(536,-1123),self.node_find(-66,-432)) #출2->도2i

        # self.global_path_msg2, path2 = self.calc_dijkstra_path_node(self.node_find(self.init_x,self.init_y),self.node_find(self.goal_x,self.goal_y))
        self.global_path_msg, path = self.global_path_msg1, path1
        self.global_data_msg = global_data()
        self.global_data_msg.nodes_idx = path["node_path"]
        self.global_data_msg.links_idx = path["link_path"]

        rate = rospy.Rate(1) # 10hz
        while not rospy.is_shutdown():
            #TODO: (11) dijkstra 이용해 만든 Global Path 정보 Publish
            # dijkstra 이용해 만든 Global Path 메세지 를 전송하는 publisher 를 만든다.

            RL_c=Realtime_listener()


            # if self.check_data!=RL_c.data:

            #     self.check_data=RL_c.data
            #     self.init_callback(RL_c.data)
            #     self.goal_callback(RL_c.data)

            #     self.global_path_msg = Path()
            #     self.global_path_msg.header.frame_id = '/map'
            #     self.HCD=[[self.egox,self.egoy],[self.init_x,self.init_y],[self.goal_x,self.goal_y]]
                
            #     # TODO 데이터를 담아서
            #     self.global_path_msg1, path1 = self.calc_dijkstra_path_node(self.node_find(self.egox,self.egoy),self.node_find(self.init_x,self.init_y))
            #     self.global_path_msg2, path2 = self.calc_dijkstra_path_node(self.node_find(self.init_x,self.init_y),self.node_find(self.goal_x,self.goal_y))
            #     self.global_path_msg, path = self.global_path_msg1, path1
            #     self.global_data_msg = global_data()
            #     self.global_data_msg.nodes_idx = path["node_path"]
            #     self.global_data_msg.links_idx = path["link_path"]


            self.global_path_pub.publish(self.global_path_msg)

            # TODO 전송
            self.global_data_pub.publish(self.global_data_msg)
            
            rate.sleep()
        else:
            print('end')

    def odom_callback(self,msg):
        self.is_odom = True
        #TODO: (4) 콜백함수에서 처음 메시지가 들어오면 초기 위치를 저장

        # gpsimu_parser.py 예제에서 Publish 해주는 Odometry 메세지 데이터를 Subscrib 한다.
        # Odometry 메세지 에 담긴 물체의 위치 데이터를 아래 변수에 넣어준다.
        self.egox = msg.pose.pose.position.x
        self.egoy = msg.pose.pose.position.y

    def init_callback(self,msg):
        long = msg['Initnode_lng']
        lat = msg['Initnode_lat']

        xy_zone = self.proj_UTM(long, lat)

        # if 문을 이용 예외처리를 하는 이유는 시뮬레이터 음영 구간 설정 센서 데이터가 0.0 으로 나오기 때문이다.
        if long == 0 and lat == 0:
            x = 0.0
            y = 0.0
        else:
            x = xy_zone[0] - 313008.55819800857
            y = xy_zone[1] - 4161698.628368007

        start_min_dis=float('inf')
        # self.init_msg=msg
        self.init_x=x
        self.init_y=y

        # for node_idx in self.nodes:
        #     node_pose_x=self.nodes[node_idx].point[0]
        #     node_pose_y=self.nodes[node_idx].point[1]
        #     start_dis = sqrt(pow(self.init_x - node_pose_x, 2) + pow(self.init_y - node_pose_y, 2))
        #     if start_dis < start_min_dis :
        #         start_min_dis=start_dis
        #         self.start_node = node_idx
        self.is_init_pose = True
    def node_find(self,x,y):
        min_dis = float('inf')
        for node_idx in self.nodes:
            node_pose_x=self.nodes[node_idx].point[0]
            node_pose_y=self.nodes[node_idx].point[1]
            start_dis = sqrt(pow(x - node_pose_x, 2) + pow(y - node_pose_y, 2))
            if start_dis < min_dis :
                min_dis=start_dis
                find_node = node_idx
        return find_node
        

        

    def goal_callback(self,msg):
        long = msg['Endnode_lng']
        lat = msg['Endnode_lat']

        xy_zone = self.proj_UTM(long, lat)

        # if 문을 이용 예외처리를 하는 이유는 시뮬레이터 음영 구간 설정 센서 데이터가 0.0 으로 나오기 때문이다.
        if long == 0 and lat == 0:
            x = 0.0
            y = 0.0
        else:
            x = xy_zone[0] - 313008.55819800857
            y = xy_zone[1] - 4161698.628368007




        goal_min_dis=float('inf')
        # self.init_msg=msg
        self.goal_x=x
        self.goal_y=y

        # for node_idx in self.nodes:
        #     node_pose_x=self.nodes[node_idx].point[0]
        #     node_pose_y=self.nodes[node_idx].point[1]
        #     goal_dis = sqrt(pow(self.goal_x - node_pose_x, 2) + pow(self.goal_y - node_pose_y, 2))

        #     if goal_dis < goal_min_dis :
        #         goal_min_dis=goal_dis
        #         self.end_node = node_idx

        self.is_goal_pose = True

    def calc_dijkstra_path_node(self, start_node, end_node):

        result, path = self.global_planner.find_shortest_path(start_node, end_node)

        #TODO: (10) dijkstra 경로 데이터를 ROS Path 메세지 형식에 맞춰 정의
        out_path = Path()
        out_path.header.frame_id = '/map'
        
        # dijkstra 경로 데이터 중 Point 정보를 이용하여 Path 데이터를 만들어 줍니다.
        # => result에 대한 true false는 안..사용하나보다.
        point_paths = path["point_path"]
        for point_path in point_paths:
            read_pose = PoseStamped()
            read_pose.pose.position.x = point_path[0]
            read_pose.pose.position.y = point_path[1]
            read_pose.pose.position.z = .0
            read_pose.pose.orientation.w = 1
            out_path.poses.append(read_pose)

        # TODO Path와 전역경로상의 노드, 링크, 점의 데이터가 담긴 딕셔너리도 같이 반환
        return (out_path, path)

class Dijkstra:
    def __init__(self, nodes, links):
        self.nodes = nodes
        self.links = links
        self.weight = self.get_weight_matrix()
        self.lane_change_link_idx = []

    def get_weight_matrix(self):
        #TODO: (3) weight 값 계산
        '''
        # weight 값 계산은 각 Node 에서 인접 한 다른 Node 까지의 비용을 계산합니다.
        # 계산된 weight 값 은 각 노드간 이동시 발생하는 비용(거리)을 가지고 있기 때문에
        # Dijkstra 탐색에서 중요하게 사용 됩니다.
        # weight 값은 딕셔너리 형태로 사용 합니다.
        # 이중 중첩된 딕셔너리 형태로 사용하며 
        # Key 값으로 Node의 Idx Value 값으로 다른 노드 까지의 비용을 가지도록 합니다.
        # 아래 코드 중 self.find_shortest_link_leading_to_node 를 완성하여 
        # Dijkstra 알고리즘 계산을 위한 Node와 Node 사이의 최단 거리를 계산합니다.
        '''
        # 초기 설정
        weight = dict() 
        for from_node_id, from_node in self.nodes.items():
            # 현재 노드에서 다른 노드로 진행하는 모든 weight
            weight_from_this_node = dict()
            for to_node_id, to_node in self.nodes.items():
                weight_from_this_node[to_node_id] = float('inf')
            # 전체 weight matrix에 추가
            weight[from_node_id] = weight_from_this_node

        for from_node_id, from_node in self.nodes.items():
            # 현재 노드에서 현재 노드로는 cost = 0
            weight[from_node_id][from_node_id] = 0

            for to_node in from_node.get_to_nodes():
                # 현재 노드에서 to_node로 연결되어 있는 링크를 찾고, 그 중에서 가장 빠른 링크를 찾아준다
                shortest_link, min_cost = self.find_shortest_link_leading_to_node(from_node,to_node)
                weight[from_node_id][to_node.idx] = min_cost           

        return weight

    def find_shortest_link_leading_to_node(self, from_node,to_node):
        """현재 노드에서 to_node로 연결되어 있는 링크를 찾고, 그 중에서 가장 빠른 링크를 찾아준다"""
        #TODO: (3) weight 값 계산
        
        # 최단거리 Link 인 shortest_link 변수와
        # shortest_link 의 min_cost 를 계산 합니다.

        # 찾아보기 귀찮아서 Node.find_shortest_link_leading_to_node 를 그대로 복붙하였다.
        # print(from_node,to_node)
        to_links = []
        Node()
        for link in from_node.get_to_links():
            if link.to_node is to_node:
                to_links.append(link)


        if len(to_links) == 0:
            raise BaseException('[ERROR] Error @ Dijkstra.find_shortest_path : Internal data error. There is no link from node (id={}) to node (id={})'.format(self.idx, to_node.idx))

        shortest_link = None
        min_cost = float('inf')
        for link in to_links:
            if link.cost < min_cost:
                min_cost = link.cost
                shortest_link = link

        return shortest_link, min_cost
        
    def find_nearest_node_idx(self, distance, s):        
        idx_list = self.nodes.keys()
        min_value = float('inf')
        min_idx = idx_list[-1]

        for idx in idx_list:
            if distance[idx] < min_value and s[idx] == False :
                min_value = distance[idx]
                min_idx = idx
        return min_idx

    def find_shortest_path(self, start_node_idx, end_node_idx): 
        #TODO: (4) Dijkstra Path 초기화 로직
        # s 초기화         >> s = [False] * len(self.nodes)
        # from_node 초기화 >> from_node = [start_node_idx] * len(self.nodes)
        '''
        # Dijkstra 경로 탐색을 위한 초기화 로직 입니다.
        # 변수 s와 from_node 는 딕셔너리 형태로 크기를 MGeo의 Node 의 개수로 설정합니다. 
        # Dijkstra 알고리즘으로 탐색 한 Node 는 변수 s 에 True 로 탐색하지 않은 변수는 False 로 합니다.
        # from_node 의 Key 값은 Node 의 Idx로
        # from_node 의 Value 값은 Key 값의 Node Idx 에서 가장 비용이 작은(가장 가까운) Node Idx로 합니다.
        # from_node 통해 각 Node 에서 가장 가까운 Node 찾고
        # 이를 연결해 시작 노드부터 도착 노드 까지의 최단 경로를 탐색합니다. 
        '''
        s = dict()
        from_node = dict() 
        for node_id in self.nodes.keys():
            s[node_id] = False
            from_node[node_id] = start_node_idx

        s[start_node_idx] = True
        distance =copy.deepcopy(self.weight[start_node_idx])

        #TODO: (5) Dijkstra 핵심 코드
        for i in range(len(self.nodes.keys()) - 1):
            selected_node_idx = self.find_nearest_node_idx(distance, s)
            s[selected_node_idx] = True            
            for j, to_node_idx in enumerate(self.nodes.keys()):
                if s[to_node_idx] == False:
                    distance_candidate = distance[selected_node_idx] + self.weight[selected_node_idx][to_node_idx]
                    if distance_candidate < distance[to_node_idx]:
                        distance[to_node_idx] = distance_candidate
                        from_node[to_node_idx] = selected_node_idx

        #TODO: (6) node path 생성
        tracking_idx = end_node_idx
        node_path = [end_node_idx]
        
        while start_node_idx != tracking_idx:
            tracking_idx = from_node[tracking_idx]
            node_path.append(tracking_idx)     

        node_path.reverse()

        #TODO: (7) link path 생성
        link_path = []
        for i in range(len(node_path) - 1):
            from_node_idx = node_path[i]
            to_node_idx = node_path[i + 1]

            from_node = self.nodes[from_node_idx]
            to_node = self.nodes[to_node_idx]

            shortest_link, min_cost = self.find_shortest_link_leading_to_node(from_node,to_node)
            link_path.append(shortest_link.idx)

        #TODO: (8) Result 판별
        if len(link_path) == 0:
            return False, {'node_path': node_path, 'link_path':link_path, 'point_path':[]}

        #TODO: (9) point path 생성
        point_path = []        
        for link_id in link_path:
            link = self.links[link_id]
            for point in link.points:
                point_path.append([point[0], point[1], 0])

        return True, {'node_path': node_path, 'link_path':link_path, 'point_path':point_path}

class Realtime_listener:
    def __init__(self):

        # rospy.init_node("realtime_listener", anonymous=True)
        # you can set a specific location like this...
        # doc_ref = db.collection(u'Ego').document(u'Ego_status')
        # start realtime listener at doc_Ref
        # doc_watch = doc_ref.on_snapshot(self.on_snapshot)

        user_ref = db.collection(u'User').document(u'User1').get().to_dict() if db.collection(u'User').document(u'User1').get().to_dict() else []
        # ego_ref = db.collection(u'Ego').document(u'Ego1').get().to_dict() if db.collection(u'Ego').document(u'Ego1').get().to_dict() else []


        # self.change_type = False
        # self.check_time = ""
        self.data = user_ref
        # self.Egodata = ego_ref
  
        # rate = rospy.Rate(2) # 2 times / 1 sec
        # while not rospy.is_shutdown():
        #     if self.change_type == 'MODIFIED':
        #         print("-----------------------")
        #         print("modified at "+{self.check_time}+" !!")
        #         print("doc_ref data : " + {self.data})
        #         print("-----------------------")

        #     elif self.change_type == "ADDED":
        #         print("-----------------------")
        #         print("added at " + {self.check_time} +"!!")
        #         print("doc_ref data : "+ {self.data})
        #         print("-----------------------")

        #     else:
        #         print('no changed...')


            # self.change_type = False
            # rate.sleep()


    # firebase reference (data type and fields)  >>  https://cloud.google.com/firestore/docs/reference/rpc/google.firestore.v1#documentchange
    # this function works only when there is a change at doc_Ref
    def on_snapshot(self, doc_snapshot, changes, read_time):
        
        # change type : 'ADDED', 'MODIFIED', 'REMOVED'
        for change in changes:
            self.change_type = change.type.name

        # you can check data here
        for doc in doc_snapshot:
            self.data =  doc.to_dict()

        # read time (based on the region where your DB is located)
        self.check_time = read_time

        callback_done.set()

if __name__ == '__main__':
    
    dijkstra_path_pub = dijkstra_path_pub()